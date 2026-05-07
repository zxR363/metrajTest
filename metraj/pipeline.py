"""High-level orchestration: DWG/DXF -> mahal -> openings -> walls -> excel/pdf.

This is the spine that the CLI and the PySide6 UI both call into.  It returns
plain dataclasses so callers can render them however they like.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from .core.cad_io import DwgConverter, DxfReader, OdaNotFoundError, RawCadModel
from .core.cad_io.dxf_reader import inventory_blocks, inventory_layers
from .core.excel import ExcelReportWriter
from .core.mapping import (
    AutodetectReport,
    LayerMap,
    PozLibrary,
    ProjectConfig,
    TipDefinitions,
    autodetect_layer_map,
    merge_into_layer_map,
)
from .core.mapping.discovery import (
    ConfigDiscoveryReport,
    discover_config_gaps,
)
from .core.openings import Opening, OpeningDetector
from .core.pozlar import IcmalAggregator, PozTotals
from .core.quantities import QuantityCalculator, QuantityOptions, RoomQuantities
from .core.reports import PdfReportBuilder, RevisionComparator
from .core.rooms import Room, RoomDetector, TipAssigner
from .core.walls import WallExtractor, WallSegment

logger = logging.getLogger(__name__)


@dataclass
class PipelineConfig:
    layer_map: LayerMap
    poz_library: PozLibrary
    tip_definitions: TipDefinitions
    project: ProjectConfig
    quantity_options: QuantityOptions = field(default_factory=QuantityOptions)
    default_height: float = 4.3

    @classmethod
    def from_directory(cls, directory: str | Path) -> "PipelineConfig":
        d = Path(directory)
        return cls(
            layer_map=LayerMap.from_yaml(d / "layer_map.yaml"),
            poz_library=PozLibrary.from_yaml(d / "poz_library.yaml"),
            tip_definitions=TipDefinitions.from_yaml(d / "tip_definitions.yaml"),
            project=ProjectConfig.from_yaml(d / "project.yaml"),
        )


@dataclass
class PipelineResult:
    model: RawCadModel
    rooms: List[Room]
    openings: List[Opening]
    quantities: List[RoomQuantities]
    walls: List[WallSegment]
    icmal: PozTotals
    layer_inventory: Dict[str, Dict[str, int]]
    block_inventory: Dict[str, int]
    autodetect_report: Optional[AutodetectReport] = None
    config_gaps: Optional[ConfigDiscoveryReport] = None
    effective_layer_map: Optional[LayerMap] = None
    excel_path: Optional[Path] = None
    pdf_path: Optional[Path] = None


class Pipeline:
    """End-to-end metraj pipeline."""

    def __init__(self, config: PipelineConfig) -> None:
        self.config = config

    def run(
        self,
        cad_path: str | Path,
        output_dir: str | Path,
        excel_name: str = "metraj.xlsx",
        pdf_name: str = "metraj.pdf",
        write_excel: bool = True,
        write_pdf: bool = True,
        oda_binary: Optional[str] = None,
        room_tip_overrides: Optional[Dict[str, Dict[str, str]]] = None,
        autodetect_layers: bool = True,
    ) -> PipelineResult:
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        # 1) Convert / read CAD
        converter = DwgConverter(binary_path=oda_binary)
        try:
            dxf_path = converter.ensure_dxf(cad_path)
        except OdaNotFoundError as exc:
            if Path(cad_path).suffix.lower() == ".dxf":
                dxf_path = Path(cad_path)
            else:
                raise RuntimeError(
                    f"DWG dosyasi yuklendi fakat ODA File Converter bulunamadi. "
                    f"Lutfen ODA File Converter'i kurun veya DXF olarak verin: {exc}"
                ) from exc
        reader = DxfReader(target_unit="m")
        model = reader.read(dxf_path)

        layer_inv = inventory_layers(model)
        block_inv = inventory_blocks(model)

        # 1.5) Autodetect: konfige tanimsiz katmanlari heuristikle eşle
        autodetect_report: Optional[AutodetectReport] = None
        effective_layer_map = self.config.layer_map
        if autodetect_layers:
            autodetect_report = autodetect_layer_map(model, base_map=self.config.layer_map)
            effective_layer_map = merge_into_layer_map(autodetect_report,
                                                      self.config.layer_map)
            if autodetect_report.unmatched:
                logger.warning(
                    "Eslesmemis %d katman: %s",
                    len(autodetect_report.unmatched),
                    ", ".join(autodetect_report.unmatched[:10]),
                )

        # 2) Rooms
        room_detector = RoomDetector(
            layer_map=effective_layer_map,
            default_height=self.config.default_height,
        )
        rooms, _stats = room_detector.detect(model)

        # Initial tip assignment from heuristics (mahal-name -> tip).
        # TipAssigner takes the active project's TipDefinitions so it picks
        # codes that actually exist in the firma's standard.
        TipAssigner(tip_definitions=self.config.tip_definitions).assign(rooms)

        # Apply per-room tip overrides supplied by the UI
        if room_tip_overrides:
            for room in rooms:
                ov = room_tip_overrides.get(room.code) or {}
                room.floor_tip = ov.get("floor_tip", room.floor_tip)
                room.wall_tip = ov.get("wall_tip", room.wall_tip)
                room.ceiling_tip = ov.get("ceiling_tip", room.ceiling_tip)
                room.skirting_tip = ov.get("skirting_tip", room.skirting_tip)

        # 3) Openings
        opening_detector = OpeningDetector(effective_layer_map, self.config.project)
        openings = opening_detector.detect(model, rooms)

        # 4) Walls
        wall_extractor = WallExtractor(
            effective_layer_map,
            self.config.project,
            default_height=self.config.default_height,
        )
        walls = wall_extractor.extract(model)

        # 5) Quantities
        quantity_calc = QuantityCalculator(self.config.quantity_options)
        quantities = quantity_calc.compute(rooms, openings)

        # 6) Icmal
        icmal_aggregator = IcmalAggregator(
            self.config.tip_definitions, self.config.poz_library
        )
        icmal = icmal_aggregator.aggregate(quantities, openings)

        # 6.5) Konfig boslugu raporu (eksik tip / eksik poz)
        gaps = discover_config_gaps(rooms, self.config.tip_definitions,
                                    self.config.poz_library)
        if gaps.has_gaps():
            logger.warning("Konfig boslugu: %s", gaps.summary())

        result = PipelineResult(
            model=model,
            rooms=rooms,
            openings=openings,
            quantities=quantities,
            walls=walls,
            icmal=icmal,
            layer_inventory=layer_inv,
            block_inventory=block_inv,
            autodetect_report=autodetect_report,
            config_gaps=gaps,
            effective_layer_map=effective_layer_map,
        )

        # 7) Reports
        if write_excel:
            writer = ExcelReportWriter()
            result.excel_path = writer.write(
                out_dir / excel_name,
                quantities=quantities,
                openings=openings,
                icmal=icmal,
                project_name=self.config.project.proje_adi,
            )
        if write_pdf:
            pdf_builder = PdfReportBuilder()
            result.pdf_path = pdf_builder.build(
                out_dir / pdf_name,
                project_name=self.config.project.proje_adi,
                quantities=quantities,
                totals=icmal,
            )
        return result
