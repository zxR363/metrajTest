"""End-to-end pipeline tests against the synthetic fixture."""
from __future__ import annotations

from pathlib import Path

import pytest

from metraj.core.cad_io import DxfReader
from metraj.core.cad_io.dxf_reader import inventory_blocks, inventory_layers
from metraj.core.excel.ground_truth import GroundTruthReader
from metraj.core.mapping import LayerMap, PozLibrary, ProjectConfig, TipDefinitions
from metraj.core.openings import OpeningDetector
from metraj.core.pozlar import IcmalAggregator
from metraj.core.quantities import QuantityCalculator
from metraj.core.rooms import RoomDetector
from metraj.core.walls import WallExtractor
from metraj.pipeline import Pipeline, PipelineConfig
from metraj.tests.fixtures import build_demo_dxf

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"


@pytest.fixture(scope="module")
def demo_dxf(tmp_path_factory) -> Path:
    target = tmp_path_factory.mktemp("dxf") / "demo.dxf"
    return build_demo_dxf(target)


@pytest.fixture(scope="module")
def config() -> PipelineConfig:
    return PipelineConfig.from_directory(CONFIG_DIR)


def test_dxf_reader(demo_dxf: Path) -> None:
    model = DxfReader(target_unit="m").read(demo_dxf)
    assert model.lines, "lines should be present"
    assert model.texts, "labels should be present"
    inv = inventory_layers(model)
    assert "A-WALL" in inv
    assert inv["A-WALL"]["line"] >= 16  # 5 rooms * 4 sides minus shared edges
    blocks = inventory_blocks(model)
    assert blocks.get("KAPI_100x240", 0) >= 4
    assert blocks.get("PENCERE_150x150", 0) >= 3


def test_room_detection(demo_dxf: Path, config: PipelineConfig) -> None:
    model = DxfReader(target_unit="m").read(demo_dxf)
    detector = RoomDetector(config.layer_map, default_height=4.3)
    rooms, stats = detector.detect(model)
    codes = {r.code for r in rooms}
    # Allow either explicit or fallback strategy to find at least 4 rooms
    assert len(rooms) >= 4
    assert any(c.startswith("Z-") for c in codes)


def test_pipeline_end_to_end(demo_dxf: Path, config: PipelineConfig, tmp_path: Path) -> None:
    pipeline = Pipeline(config)
    result = pipeline.run(
        cad_path=demo_dxf,
        output_dir=tmp_path,
        excel_name="metraj.xlsx",
        pdf_name="metraj.pdf",
    )
    assert len(result.rooms) >= 4
    assert len(result.openings) >= 4
    assert len(result.walls) >= 1
    assert result.excel_path is not None and result.excel_path.exists()
    assert result.pdf_path is not None and result.pdf_path.exists()
    # Assigning tips and checking icmal totals
    for room in result.rooms:
        room.floor_tip = "DS3"
        room.wall_tip = "DV1"
        room.ceiling_tip = "TV1"
        room.skirting_tip = "SP_TER"
    quantities = QuantityCalculator().compute(result.rooms, result.openings)
    icmal = IcmalAggregator(config.tip_definitions, config.poz_library).aggregate(
        quantities, result.openings)
    assert icmal.grand_total > 0
    assert icmal.by_kategori["DOSEME"] > 0
    assert icmal.by_kategori["DUVAR"] > 0


def test_ground_truth_reader(tmp_path: Path) -> None:
    """If the firma's reference workbook is in the workspace, ensure it parses."""
    sample = Path(__file__).resolve().parents[2] / "YM-K-Amfi Mahal Metraj_R22.xlsx"
    if not sample.exists():
        pytest.skip("Ground-truth workbook not in repo")
    book = GroundTruthReader().read(sample)
    assert len(book.rooms) > 100
    total_area = sum(r.area for r in book.rooms)
    assert total_area > 1000


def test_walls_extraction(demo_dxf: Path, config: PipelineConfig) -> None:
    model = DxfReader(target_unit="m").read(demo_dxf)
    extractor = WallExtractor(config.layer_map, config.project, default_height=4.3)
    segments = extractor.extract(model)
    assert segments, "at least one wall segment expected"
    totals = extractor.aggregate(segments)
    assert totals.by_band_length, "wall totals should aggregate per band"
