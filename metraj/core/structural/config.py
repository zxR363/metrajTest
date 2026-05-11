"""Yapisal metraj konfigurasyonu."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Set

import yaml

from .calculator import CalcParams


ExcelLayout = Literal["generic", "kumluca"]


def _deep_merge_mapping(base: dict, override: dict) -> dict:
    """Ikinci sozluk birincinin uzerine yazilir; ic ice dict'ler birlestirilir."""
    out = dict(base)
    for key, val in override.items():
        if key == "extends":
            continue
        if (
            key in out
            and isinstance(out[key], dict)
            and isinstance(val, dict)
        ):
            out[key] = _deep_merge_mapping(out[key], val)
        else:
            out[key] = val
    return out


def _load_structural_yaml_dict(path: Path, chain: Optional[Set[Path]] = None) -> dict:
    """YAML yukler; ``extends: dosya.yaml`` ile taban dosya ile birlestirir."""
    path = path.resolve()
    chain = chain or set()
    if path in chain:
        raise ValueError(f"YAML extends dongusu: {path}")
    chain = set(chain)
    chain.add(path)

    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError(f"YAML kok nesnesi sozluk olmali: {path}")

    extends = data.pop("extends", None)
    if extends:
        base_path = (path.parent / str(extends)).resolve()
        if not base_path.is_file():
            raise FileNotFoundError(f"extends bulunamadi: {base_path}")
        base_data = _load_structural_yaml_dict(base_path, chain)
        data = _deep_merge_mapping(base_data, data)
    return data


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
    #: ``excel_layout=kumluca`` icin kot on eki kirpilacak etiketler (YAML override);
    #: bos liste ise gt_io.py icindeki ``KUMLUCA_STRIP_KOT_PREFIX_REST`` default'u kullanilir.
    strip_kot_prefix_labels: List[str] = field(default_factory=list)
    #: Faz 1: INSERT (block reference) entity'lerini block tanimindan transform ederek
    #: polyline/hatch listelerine acsin mi? Kolon/kapi blok kullanan firma cizimlerinde
    #: gerekli; varsayilan kapali (geri uyum + olasi mukerrer sayim onleme).
    explode_inserts: bool = False
    #: Faz 1: Disardaki YAML dosyasi (``signal_hints`` blogu); skor sistemi
    #: bu dosyadaki ``name_aliases`` ve ``color_hints``'i okur. None ise sadece
    #: ``score_signal_hints`` inline kullanilir.
    signal_hints_path: Optional[str] = None
    #: Faz 1: Inline signal_hints sozlugu (YAML'in eşdeğeri). ``signal_hints_path``
    #: bir dosyadan okunduktan sonra bu sozluk uzerine MERGE edilir (priorite: inline).
    signal_hints: Dict[str, Any] = field(default_factory=dict)
    #: Faz 2: Plan basligi locale ad ("tr" / "en") veya YAML dosyasi yolu.
    #: None ise default Turkce locale kullanilir.
    plan_labels_locale: Optional[str] = None
    #: Faz 2: Plan kumeleme ekseni — "x" (yatay layout, Kumluca default),
    #: "y" (dusey layout) ya da "auto" (her ikisi denenir).
    plan_cluster_axis: str = "x"
    #: Faz 3: Geometrik siniflandirma esikleri (column_max_aspect, wall_min_aspect,
    #: slab_min_area_m2, vb.) — ``GeometricThresholds.from_dict`` ile yuklenir.
    geometric_thresholds: Dict[str, float] = field(default_factory=dict)
    #: Faz 3: ``True`` ise pipeline ``find_classification_conflicts`` calistirir,
    #: layer-bazli ile geometric_kind uyusmazliklarini result'a ekler.
    classification_conflict_check: bool = True
    #: Faz 3: ``True`` ise extractor standalone LINE entity'leri (DXF LINE,
    #: polyline degil) acik kiris adayi olarak ekler.
    include_standalone_lines: bool = False
    #: Faz 5: Proje-bazli kullanici feedback JSON dosyasi (FeedbackStore). Pipeline
    #: baslangicinda yuklenir, ``structural_layer_include_kind`` /
    #: ``comparison_label_aliases`` / ``structural_layer_exclude`` uzerine merge edilir.
    feedback_store_path: Optional[str] = None
    #: Katman adi -> yapisal tur (``ElementKind``), autodetect uzerine yazar.
    structural_layer_include_kind: Dict[str, str] = field(default_factory=dict)
    #: Otomatik bulunsa bile bu katmanlardan geometri cikarma.
    structural_layer_exclude: List[str] = field(default_factory=list)

    @classmethod
    def from_file(cls, path: str | Path) -> "StructuralConfig":
        path = Path(path)
        data = _load_structural_yaml_dict(path)
        cfg = cls.from_dict(data)
        # Referans Excel yolu YAML dosyasina gore cozumle
        ref = cfg.reference_excel_path
        if ref and not Path(ref).is_absolute():
            candidate = (path.parent / ref).resolve()
            if candidate.is_file():
                cfg.reference_excel_path = str(candidate)
        # Faz 1: signal_hints_path goreli ise YAML dosyasi yanindan coz
        if cfg.signal_hints_path:
            sp = Path(cfg.signal_hints_path)
            if not sp.is_absolute():
                cand = (path.parent / sp).resolve()
                if cand.is_file():
                    cfg.signal_hints_path = str(cand)
        # Faz 5: feedback_store_path benzer cozumleme
        if cfg.feedback_store_path:
            fp = Path(cfg.feedback_store_path)
            if not fp.is_absolute():
                cand = (path.parent / fp).resolve()
                cfg.feedback_store_path = str(cand)
        return cfg

    def load_signal_hints(self) -> Dict[str, Any]:
        """``signal_hints_path`` (dosyadan) + ``signal_hints`` (inline) birlestir.

        Inline blogu dosya uzerine YAZAR (priorite: inline). Hicbir kaynak yoksa
        bos sozluk doner; skor sistemi sadece ad regex + geometriyle calisir.
        """
        out: Dict[str, Any] = {}
        if self.signal_hints_path:
            p = Path(self.signal_hints_path)
            if p.is_file():
                with open(p, "r", encoding="utf-8") as fh:
                    loaded = yaml.safe_load(fh) or {}
                if isinstance(loaded, dict):
                    out = _deep_merge_mapping(out, loaded)
        if self.signal_hints:
            out = _deep_merge_mapping(out, dict(self.signal_hints))
        return out

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
        strip_labels_raw = data.get("strip_kot_prefix_labels") or []
        if not isinstance(strip_labels_raw, list):
            strip_labels_raw = []
        strip_labels = [str(x) for x in strip_labels_raw]
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
            strip_kot_prefix_labels=strip_labels,
            explode_inserts=bool(data.get("explode_inserts", False)),
            signal_hints_path=(
                str(data["signal_hints_path"])
                if data.get("signal_hints_path") else None
            ),
            signal_hints=(
                dict(data.get("signal_hints") or {})
                if isinstance(data.get("signal_hints"), dict) else {}
            ),
            plan_labels_locale=(
                str(data["plan_labels_locale"])
                if data.get("plan_labels_locale") else None
            ),
            plan_cluster_axis=str(data.get("plan_cluster_axis", "x")),
            geometric_thresholds=(
                {str(k): float(v) for k, v in (data.get("geometric_thresholds") or {}).items()
                 if isinstance(v, (int, float))}
                if isinstance(data.get("geometric_thresholds"), dict) else {}
            ),
            classification_conflict_check=bool(data.get("classification_conflict_check", True)),
            include_standalone_lines=bool(data.get("include_standalone_lines", False)),
            feedback_store_path=(
                str(data["feedback_store_path"])
                if data.get("feedback_store_path") else None
            ),
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
