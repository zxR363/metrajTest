"""Faz 4: Otomatik metraj profili (CalcParams) fitting.

Profile fitter, kullanicidan bir CAD dosyasi + referans Excel cifti alir; pipeline'i
"saf geometri" (params=CalcParams varsayilan) modunda calistirir; baseline cikti ile
referans Excel satirlarini kategori bazinda eslestirir; ve her ilgili CalcParams
alani icin **closed-form** olarak ``fitted_scale = target_sum / computed_sum``
hesaplar.

Kullanim:

.. code-block:: python

   from metraj.core.structural.profile_fitter import fit_profile_from_dxf
   result = fit_profile_from_dxf(
       cad_path="proje.dxf",
       reference_excel="referans.xlsx",
       output_yaml="profile.yaml",
   )
   print(result.fitted_params)
   print(result.report)

CLI:

.. code-block:: bash

   python -m metraj.cli structural-fit proje.dxf referans.xlsx -o profile.yaml

Sapma analizi:
* Lineer model: ``target = baseline * scale``. Iliski cogu CalcParams alaninda
  birebir geometrik (alan*scale, perimetre*scale). Bu yuzden closed-form
  ``target / baseline`` cogu kez yeterlidir.
* Kat-bazli dict alanlar (``doseme_net_scale_by_floor_label`` vb.) ilk surumde
  tek global olcege indirgenir; ileride iki-asamali fit eklenebilir.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import yaml

from .calculator import CalcParams, CalcRow, StructuralReport, calculate
from .config import StructuralConfig
from .gt_io import parse_kumluca_reference
from .pipeline import StructuralPipeline

logger = logging.getLogger(__name__)


@dataclass
class FitTarget:
    """Bir ``CalcParams`` alani icin hangi computed satirlarinin toplamı target'a eslenir.

    ``category_filter``: ``CalcRow.category`` ile eslen (KOLON, PERDE, KIRIS, ...).
    ``section_filter``: ``"formwork"`` veya ``"concrete"`` (her ikisi de mumkun).
    ``label_substring_filter``: opsiyonel; satir etiketi bu substring'i icermeli.
    ``min_baseline_total``: cok kucuk baseline'lar fit'i bozar; bu esikten dusuk
    olanlar atlanir.
    """

    field_name: str
    category_filter: Sequence[str]
    section_filter: Sequence[str]
    label_substring_filter: Optional[str] = None
    min_baseline_total: float = 0.05


# Ana scale alanlari (Kumluca kalibrasyonu ile uyum: hepsi 0.5 / ~1.0 araliginda).
_FIT_TARGETS: List[FitTarget] = [
    FitTarget("column_formwork_strip_fraction", ["KOLON"], ["formwork"]),
    FitTarget("column_concrete_section_fraction", ["KOLON"], ["concrete"]),
    FitTarget("shear_wall_concrete_section_fraction", ["PERDE"], ["concrete"]),
    FitTarget("beam_formwork_length_fraction", ["KIRIS"], ["formwork"]),
    FitTarget("beam_concrete_section_fraction", ["KIRIS"], ["concrete"]),
    # DOSEME hem kalip hem beton; ayni geometrik scale (slab_net_area_fraction).
    FitTarget("slab_net_area_fraction", ["DOSEME"], ["formwork", "concrete"]),
    FitTarget("foundation_plan_formwork_scale", ["TEMEL"], ["formwork"]),
    FitTarget("foundation_concrete_section_fraction", ["TEMEL"], ["concrete"]),
    FitTarget("grobeton_formwork_gt_scale", ["GROBETON"], ["formwork"]),
    # Asansor: 3 sahnenin tek satira indirgenmesi (Kumluca'da 1/3)
    FitTarget("elevator_shaft_quantity_scale",
              ["ASANSOR"], ["formwork", "concrete"]),
    # Faz 4 v3 notu: parapet_concrete_volume_fraction ve kolon_head_minha_scale
    # tek-param fit ile karsiliklarini bulamadi (baseline-reference kategori
    # uyumsuzluklari). BETON sapmanin geri kalani (~%9) `beam_split_*` ailesi
    # ile cozulebilir — multi-kat plan analizi gerektirir; sahsen kalibrasyon
    # sihirbazi (Faz 7) veya multi-reference median (Faz 6) ile cozumlenir.
]


@dataclass
class FloorDictFitTarget:
    """Faz 4 v2: kat-bazli dict ``CalcParams`` alanlari icin fit hedefi.

    Global scale (1. asama) sonrasi her katin baseline'inda kalan residual'i,
    o kategorinin kat-bazli scale sozlugune yazariz. Bu sayede Kumluca'nin
    ``doseme_net_scale_by_floor_label`` gibi ince-ayarlari otomatize edilir.
    """

    field_name: str           # CalcParams dict alani (orn. doseme_net_scale_by_floor_label)
    category_filter: Sequence[str]
    section_filter: Sequence[str]
    label_substring_filter: Optional[str] = None
    #: Bu eşigin üzerinde (max/min) varyansı olursa kat-bazlı dict yazılır.
    min_variance_ratio: float = 1.03
    #: Tek bir kat icin minimum baseline (cok kucuk degerler fit'i bozar)
    min_baseline_per_floor: float = 0.5


# Kat-bazli dict alanlari (Kumluca yaml'ndaki kalibrasyonla birebir).
_FLOOR_DICT_TARGETS: List[FloorDictFitTarget] = [
    # Doseme: hem kalip hem beton kat-bazli scale gerektirebilir.
    # Kumluca'da `doseme_net_scale_by_floor_label` ve ayri olarak
    # `doseme_concrete_net_scale_by_floor_label` var.
    FloorDictFitTarget(
        "doseme_net_scale_by_floor_label", ["DOSEME"], ["formwork"],
    ),
    FloorDictFitTarget(
        "doseme_concrete_net_scale_by_floor_label", ["DOSEME"], ["concrete"],
    ),
    FloorDictFitTarget(
        "beam_formwork_floor_scale", ["KIRIS"], ["formwork"],
    ),
    FloorDictFitTarget(
        "beam_concrete_floor_scale", ["KIRIS"], ["concrete"],
    ),
    FloorDictFitTarget(
        "parapet_formwork_floor_scale", ["PARAPET"], ["formwork"],
        min_baseline_per_floor=0.1,
    ),
]


@dataclass
class FitFieldResult:
    """Tek bir alan icin fit sonucu."""

    field_name: str
    fitted_value: float
    baseline_total: float
    reference_total: float
    matched_rows: int


@dataclass
class FitResult:
    """``fit_profile_from_dxf`` cikisi."""

    fitted_params: CalcParams
    field_results: List[FitFieldResult] = field(default_factory=list)
    baseline_formwork_total: float = 0.0
    baseline_concrete_total: float = 0.0
    reference_formwork_total: float = 0.0
    reference_concrete_total: float = 0.0
    yaml_path: Optional[Path] = None
    report: str = ""


def _section_rows(report: StructuralReport, section: str) -> List[CalcRow]:
    if section == "formwork":
        return list(report.formwork_rows)
    if section == "concrete":
        return list(report.concrete_rows)
    return []


def _matches_target(row: CalcRow, target: FitTarget) -> bool:
    if row.category not in set(target.category_filter):
        return False
    if target.label_substring_filter:
        if target.label_substring_filter.upper() not in row.label.upper():
            return False
    return True


def _sum_matching(
    report: StructuralReport, target: FitTarget,
) -> tuple[float, int]:
    """``target``'i tutturan satirlarin total toplami + sayisi."""
    total = 0.0
    n = 0
    for section in target.section_filter:
        for row in _section_rows(report, section):
            if _matches_target(row, target):
                total += float(row.total)
                n += 1
    return total, n


def _fit_one_field(
    target: FitTarget,
    baseline: StructuralReport,
    reference: StructuralReport,
) -> Optional[FitFieldResult]:
    b_total, b_n = _sum_matching(baseline, target)
    r_total, _r_n = _sum_matching(reference, target)
    if b_n == 0 or abs(b_total) < target.min_baseline_total:
        return None
    if abs(r_total) < 1e-9:
        # Referansta sifir -> scale=0 (bu alan o projede yok)
        return FitFieldResult(
            field_name=target.field_name,
            fitted_value=0.0,
            baseline_total=b_total,
            reference_total=r_total,
            matched_rows=b_n,
        )
    fitted = r_total / b_total
    return FitFieldResult(
        field_name=target.field_name,
        fitted_value=fitted,
        baseline_total=b_total,
        reference_total=r_total,
        matched_rows=b_n,
    )


def _floor_key(
    label: Optional[str],
    floor_aliases: Optional[Dict[str, str]] = None,
) -> Optional[str]:
    """CalcRow.floor_label normalizasyonu (yaml dict anahtari icin).

    Kumluca yaml'larinda kullanilan format: "0,00", "+2,85", "+5,70", "CATI",
    "TEMEL". Referans Excel ise farkli kot kullanabilir ("3,00", "6,00", ...).
    ``floor_aliases``: kot esleme sozlugu (KUMLUCA_DEFAULT_COMPARE_ALIASES gibi);
    burada baseline kotlarini referans Excel formatina cevirir, boylece
    ``+2,85`` baseline ile ``3,00`` reference ayni anahtara dusurulur.
    """
    if not label:
        return None
    s = str(label).strip()
    if s.upper() in {"TEMEL", "CATI", "ÇATI"}:
        # CATI bir alias: "CATI" -> "15,00" Kumluca'da
        if floor_aliases:
            ali = floor_aliases.get(s.upper())
            if ali:
                return ali
        return s.upper()
    # +0,00 -> 0,00
    raw = s.lstrip("+")
    if floor_aliases and raw in floor_aliases:
        return floor_aliases[raw]
    return raw if s.startswith("+") and raw == "0,00" else s


def _fit_floor_dict(
    target: FloorDictFitTarget,
    baseline_after_global: StructuralReport,
    reference: StructuralReport,
    floor_aliases: Optional[Dict[str, str]] = None,
) -> Dict[str, float]:
    """``target`` icin kat-bazli scale sozlugu uretir (varyans yuksekse).

    Algoritma:
      1. Baseline satirlarini **native floor_label** ile grupla (calculator'in
         okuyacagi key: ``+2,85`` gibi).
      2. Reference satirlarini referans formatinda grupla (``3,00``).
      3. Her baseline native key icin ``ref_key = floor_aliases[native_or_lstrip(+)]``;
         bu ref_key altinda referans toplamini al; scale = ref_total / base_total.
      4. Donen sozlugun key'leri **baseline native** (calculator dict.get(label)
         bunu eslemede kullanir).
    """
    base_per_native: Dict[str, float] = {}
    ref_per_norm: Dict[str, float] = {}
    cat_set = set(target.category_filter)

    for section in target.section_filter:
        for row in _section_rows(baseline_after_global, section):
            if row.category not in cat_set:
                continue
            if target.label_substring_filter and \
                    target.label_substring_filter.upper() not in row.label.upper():
                continue
            # Baseline: native floor_label (calculator dict'i bu formatla okur)
            native = row.floor_label
            if not native:
                continue
            base_per_native[native] = base_per_native.get(native, 0.0) + float(row.total)
        for row in _section_rows(reference, section):
            if row.category not in cat_set:
                continue
            if target.label_substring_filter and \
                    target.label_substring_filter.upper() not in row.label.upper():
                continue
            fl = _floor_key(row.floor_label)
            if fl is None:
                continue
            ref_per_norm[fl] = ref_per_norm.get(fl, 0.0) + float(row.total)

    def _native_to_ref(native: str) -> str:
        s = str(native).strip()
        # alias sozlugu kontrol et (CATI -> 15,00 gibi)
        if floor_aliases:
            for key in (s, s.upper(), s.lstrip("+")):
                if key in floor_aliases:
                    return floor_aliases[key]
        # default: +2,85 -> 2,85, "0,00" -> "0,00"
        return s.lstrip("+")

    scales: Dict[str, float] = {}
    for native, b_tot in base_per_native.items():
        if abs(b_tot) < target.min_baseline_per_floor:
            continue
        ref_key = _native_to_ref(native)
        r_tot = ref_per_norm.get(ref_key)
        if r_tot is None or abs(r_tot) < 1e-9:
            continue
        scales[native] = r_tot / b_tot

    if len(scales) < 2:
        return {}

    vals = [v for v in scales.values() if v > 0]
    if len(vals) < 2:
        return {}
    spread = max(vals) / min(vals)
    if spread < target.min_variance_ratio:
        return {}  # varyans yetersiz, global scale yeterli

    return scales


def _baseline_config(reference_excel: Path) -> StructuralConfig:
    """Saf geometri (params=varsayilan CalcParams) ile pipeline calistirmak icin
    config; Kumluca-tarzi referansa eslesmek icin excel_layout=kumluca aliases
    aktif birakilir, ama compare_to_reference kapali (cikti baseline'dir)."""
    cfg = StructuralConfig(
        project_name="profile_fit_baseline",
        params=CalcParams(),
        reference_excel_path=str(reference_excel),
        excel_layout="kumluca",  # Kumluca-style aliases ile eslesim
        compare_to_reference=False,
        snap_rows_to_reference=False,
    )
    return cfg


def fit_profile_from_dxf(
    cad_path: str | Path,
    reference_excel: str | Path,
    *,
    output_yaml: Optional[str | Path] = None,
    base_config: Optional[StructuralConfig] = None,
    two_stage_fit: bool = True,
) -> FitResult:
    """Bir DXF + referans Excel'den ``CalcParams``'i otomatik fit eder.

    ``base_config`` verilirse, pipeline o config ile (kendi katman override'lari
    + signal_hints + plan_cluster_axis ile) calistirilir; ``params`` alani
    ``CalcParams()`` (varsayilan) ile degistirilir (baseline icin) ve referans
    Excel yolu set edilir. Bu sayede fitter kullanici layer overrideleri ile
    calisir.
    """
    cad_path = Path(cad_path)
    reference_excel = Path(reference_excel)

    # 1) Baseline: saf geometri pipeline'i (params=CalcParams varsayilan)
    if base_config is not None:
        cfg = StructuralConfig(
            **{**base_config.__dict__,
               "params": CalcParams(),
               "reference_excel_path": str(reference_excel),
               "compare_to_reference": False,
               "snap_rows_to_reference": False,
               "project_name": base_config.project_name + " [profile_fit_baseline]"},
        )
    else:
        cfg = _baseline_config(reference_excel)

    pipe = StructuralPipeline(config=cfg)
    res = pipe.run(cad_path=cad_path, output_dir="build/_fit_tmp",
                   write_excel=False, write_diagnostics=False)
    baseline_report = res.report

    # 2) Referans Excel
    reference_report = parse_kumluca_reference(reference_excel)

    # 3) 1. asama: global scale alanlarini closed-form fit
    field_results: List[FitFieldResult] = []
    fitted_params = CalcParams()
    for target in _FIT_TARGETS:
        fr = _fit_one_field(target, baseline_report, reference_report)
        if fr is None:
            continue
        field_results.append(fr)
        # CalcParams alanina ata
        if hasattr(fitted_params, target.field_name):
            try:
                setattr(fitted_params, target.field_name, float(fr.fitted_value))
            except Exception:
                logger.warning("CalcParams set failed: %s -> %s",
                               target.field_name, fr.fitted_value)

    # 4) 2. asama (Faz 4 v2): kat-bazli dict alanlar
    floor_dict_summary: Dict[str, Dict[str, float]] = {}
    if two_stage_fit:
        # Kumluca-stili kot eslemesi (baseline +2,85 -> reference 3,00)
        from .gt_io import merge_comparison_aliases  # geçici local import
        layout = getattr(cfg, "excel_layout", "kumluca")
        aliases_user = getattr(cfg, "comparison_label_aliases", None)
        aliases = merge_comparison_aliases(layout, aliases_user)
        # Sadece kot-eslemeleri tut (anahtar = X,XX veya CATI/TEMEL/GROBETON)
        import re as _re
        floor_aliases = {
            k: v for k, v in aliases.items()
            if _re.fullmatch(r"\d+,\d{2}", k) or k.upper() in {"CATI", "ÇATI", "TEMEL", "GROBETON"}
        }
        # smodel'i bellekten yeniden hesapla (DXF tekrar parse etmiyoruz)
        fitted_global_report = calculate(res.smodel, fitted_params)
        for fdt in _FLOOR_DICT_TARGETS:
            scales = _fit_floor_dict(
                fdt, fitted_global_report, reference_report,
                floor_aliases=floor_aliases,
            )
            if not scales:
                continue
            if hasattr(fitted_params, fdt.field_name):
                try:
                    setattr(fitted_params, fdt.field_name, dict(scales))
                    floor_dict_summary[fdt.field_name] = dict(scales)
                except Exception:
                    logger.warning("CalcParams dict set failed: %s",
                                   fdt.field_name)

    # 5) Genel toplamlar
    base_form = baseline_report.formwork_total_m2
    base_conc = baseline_report.concrete_total_m3
    ref_form = sum(r.total for r in reference_report.formwork_rows)
    ref_conc = sum(r.total for r in reference_report.concrete_rows)

    report_lines = [
        "# Profile Fit Raporu",
        f"CAD: {cad_path}",
        f"Referans: {reference_excel}",
        "",
        f"Baseline KALIP toplam: {base_form:.2f} m2",
        f"Referans KALIP toplam: {ref_form:.2f} m2",
        f"Baseline BETON toplam: {base_conc:.2f} m3",
        f"Referans BETON toplam: {ref_conc:.2f} m3",
        "",
        "## 1. asama: global olcek alanlari",
    ]
    for fr in field_results:
        report_lines.append(
            f"  - {fr.field_name}: {fr.fitted_value:.4f}  "
            f"(baseline={fr.baseline_total:.2f}, ref={fr.reference_total:.2f}, "
            f"matched_rows={fr.matched_rows})"
        )
    if floor_dict_summary:
        report_lines.append("")
        report_lines.append("## 2. asama: kat-bazli ince ayar (varyans > %3)")
        for fld, scales in floor_dict_summary.items():
            scale_strs = ", ".join(f"{k}={v:.3f}" for k, v in scales.items())
            report_lines.append(f"  - {fld}: {{{scale_strs}}}")
    report_text = "\n".join(report_lines)

    yaml_path: Optional[Path] = None
    if output_yaml is not None:
        yaml_path = Path(output_yaml)
        dump_fitted_yaml(
            fitted_params, yaml_path,
            project_name=f"Profile fit ({cad_path.stem})",
            reference_excel_relative=_relative_to_yaml(reference_excel, yaml_path),
        )

    return FitResult(
        fitted_params=fitted_params,
        field_results=field_results,
        baseline_formwork_total=base_form,
        baseline_concrete_total=base_conc,
        reference_formwork_total=ref_form,
        reference_concrete_total=ref_conc,
        yaml_path=yaml_path,
        report=report_text,
    )


def _relative_to_yaml(target: Path, yaml_path: Path) -> str:
    """Yaml dosyasinin yanindan target'a goreli yolu uretir (yedek: absolute)."""
    try:
        return str(Path(target).resolve().relative_to(yaml_path.parent.resolve()))
    except Exception:
        return str(Path(target).resolve())


def dump_fitted_yaml(
    params: CalcParams,
    output_path: str | Path,
    *,
    project_name: str = "Fitted profile",
    reference_excel_relative: Optional[str] = None,
) -> Path:
    """``CalcParams``'i ``StructuralConfig.from_file`` ile yuklenebilir YAML'a yazar."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Sadece varsayilandan farkli alanlari yaz (kisa YAML)
    default = CalcParams()
    diff: Dict[str, Any] = {}
    for fld in params.__dataclass_fields__:
        if fld in ("storey_heights",):  # plan-bazli, fit etmiyoruz
            continue
        cur = getattr(params, fld)
        d = getattr(default, fld)
        if isinstance(cur, dict):
            if cur:
                diff[fld] = dict(cur)
        elif isinstance(cur, (int, float)):
            if abs(float(cur) - float(d)) > 1e-9:
                diff[fld] = float(cur)
        elif cur != d:
            diff[fld] = cur

    payload: Dict[str, Any] = {
        "project_name": project_name,
        "excel_layout": "kumluca",
        "compare_to_reference": True,
        "validation_tolerance": 0.01,
        "snap_rows_to_reference": False,
        "params": diff,
    }
    if reference_excel_relative:
        payload["reference_excel_path"] = reference_excel_relative

    with open(output_path, "w", encoding="utf-8") as fh:
        fh.write("# Otomatik fit edilmis profil (Faz 4 profile_fitter)\n")
        fh.write("# Sapmasi yuksek alanlari kullanici manuel ince-ayar yapabilir.\n\n")
        yaml.safe_dump(payload, fh, allow_unicode=True, sort_keys=False)
    return output_path


__all__ = [
    "FitTarget",
    "FitFieldResult",
    "FitResult",
    "fit_profile_from_dxf",
    "dump_fitted_yaml",
]
