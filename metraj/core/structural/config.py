"""Yapisal metraj konfigurasyonu."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Literal, Optional

import yaml

from .calculator import CalcParams


ExcelLayout = Literal["generic", "kumluca"]


@dataclass
class StructuralFloorEntry:
    label: str
    elevation_m: Optional[float] = None
    storey_height_m: float = 2.85


@dataclass
class StructuralConfig:
    project_name: str = "Yapisal Metraj"
    floors: List[StructuralFloorEntry] = field(default_factory=list)
    params: CalcParams = field(default_factory=CalcParams)
    expected_floor_count: Optional[int] = None
    floor_label_layers: List[str] = field(default_factory=list)
    #: Dogrulama icin referans Excel (yalnizca ``compare_to_reference`` karsilastirmasi; rakam kaynagi degil).
    reference_excel_path: Optional[str] = None
    #: ``kumluca``: A KALIP / A  BETON sutunlari ornekRef ile ayni yerlesimde.
    excel_layout: ExcelLayout = "generic"
    #: Hesap sonrasi eslesen satirlari referansa yapistirir (sapmayi gizler; kalibrasyon gelistirmesi icin).
    snap_rows_to_reference: bool = False
    #: Varsa referans Excel ile karsilastir (cikti DWG hesabi); ``dogrulama_ozeti.txt``.
    compare_to_reference: bool = False
    #: ``compare_to_reference`` icin goreli sapma esigi (ornek: 0.01 = %%1).
    validation_tolerance: float = 0.01
    #: YAML ile kiyaslama anahtari takma adlari (``comparison_label_aliases``).
    comparison_label_aliases: Dict[str, str] = field(default_factory=dict)
    #: Katman adi -> yapisal tur (``ElementKind``), autodetect uzerine yazar.
    structural_layer_include_kind: Dict[str, str] = field(default_factory=dict)
    #: Otomatik bulunsa bile bu katmanlardan geometri cikarma.
    structural_layer_exclude: List[str] = field(default_factory=list)

    @classmethod
    def from_file(cls, path: str | Path) -> "StructuralConfig":
        path = Path(path)
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        cfg = cls.from_dict(data)
        # Referans Excel yolu YAML dosyasina gore cozumle
        ref = cfg.reference_excel_path
        if ref and not Path(ref).is_absolute():
            candidate = (path.parent / ref).resolve()
            if candidate.is_file():
                cfg.reference_excel_path = str(candidate)
        return cfg

    @classmethod
    def from_dict(cls, data: dict) -> "StructuralConfig":
        floors_raw = data.get("floors") or []
        floors = [
            StructuralFloorEntry(
                label=str(f.get("label", "?")),
                elevation_m=f.get("elevation_m"),
                storey_height_m=float(f.get("storey_height_m", 2.85)),
            )
            for f in floors_raw
        ]
        params_raw = data.get("params") or {}
        params = CalcParams(**{k: v for k, v in params_raw.items()
                               if k in CalcParams.__dataclass_fields__})
        # Storey heights map: kat etiketinden ozel yukseklik
        if floors:
            params.storey_heights = {f.label: f.storey_height_m for f in floors}
        ref_path = data.get("reference_excel_path") or data.get("reference_excel")
        xl = data.get("excel_layout", "generic")
        if xl not in ("generic", "kumluca"):
            xl = "generic"
        snap = bool(data.get("snap_rows_to_reference", False))
        compare_ref = bool(data.get("compare_to_reference", False))
        val_tol = float(data.get("validation_tolerance", 0.01))
        cmp_aliases = data.get("comparison_label_aliases") or {}
        if not isinstance(cmp_aliases, dict):
            cmp_aliases = {}
        cmp_aliases = {str(k): str(v) for k, v in cmp_aliases.items()}
        inc = data.get("structural_layer_include_kind") or {}
        if not isinstance(inc, dict):
            inc = {}
        inc = {str(k): str(v) for k, v in inc.items()}
        exc = data.get("structural_layer_exclude") or []
        if not isinstance(exc, list):
            exc = []
        exc = [str(x) for x in exc]
        return cls(
            project_name=str(data.get("project_name", "Yapisal Metraj")),
            floors=floors,
            params=params,
            expected_floor_count=data.get("expected_floor_count"),
            floor_label_layers=list(data.get("floor_label_layers", [])),
            reference_excel_path=str(ref_path) if ref_path else None,
            excel_layout=xl,  # type: ignore[arg-type]
            snap_rows_to_reference=snap,
            compare_to_reference=compare_ref,
            validation_tolerance=val_tol,
            comparison_label_aliases=cmp_aliases,
            structural_layer_include_kind=inc,
            structural_layer_exclude=exc,
        )


# Generic default: Kumluca tarzi 6 katli yapi
DEFAULT_FLOORS_GENERIC = [
    StructuralFloorEntry(label="TEMEL", elevation_m=-3.00, storey_height_m=2.85),
    StructuralFloorEntry(label="0,00", elevation_m=0.00, storey_height_m=2.85),
    StructuralFloorEntry(label="3,00", elevation_m=3.00, storey_height_m=2.85),
    StructuralFloorEntry(label="6,00", elevation_m=6.00, storey_height_m=2.85),
    StructuralFloorEntry(label="9,00", elevation_m=9.00, storey_height_m=2.85),
    StructuralFloorEntry(label="12,00", elevation_m=12.00, storey_height_m=2.85),
    StructuralFloorEntry(label="15,00", elevation_m=15.00, storey_height_m=2.85),
]


def default_config() -> StructuralConfig:
    return StructuralConfig(
        project_name="Yapisal Metraj (jenerik)",
        floors=list(DEFAULT_FLOORS_GENERIC),
        params=CalcParams(
            storey_heights={f.label: f.storey_height_m for f in DEFAULT_FLOORS_GENERIC},
        ),
        expected_floor_count=len(DEFAULT_FLOORS_GENERIC),
    )
