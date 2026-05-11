"""Faz 6: Multi-reference profil egitimi.

N adet ``(CAD, referans Excel)`` cifti verir; her birinden ``profile_fitter`` ile
fit edilmis ``CalcParams`` cikarir; alan-bazinda median/IQR'i hesaplayip
**"default profile"** uretir. Yeni bir proje icin referans Excel olmasa bile
bu default profil ile pipeline kosulabilir — ilk-vurus icin makul taban.

Cikis dosyalari:
* ``trained_profile.yaml`` — median CalcParams (StructuralConfig.from_file ile yuklenir).
* ``training_report.md`` — her alan icin: median, mean, std, IQR, outlier projeler.

Leave-one-out cross-validation (opsiyonel, ``cross_validate=True``):
* Her projeyi dislayip kalan N-1'in trained profile'i ile o projeyi kosturur,
  sapma raporu doner. Genelleme bench'i icin guvenilir veri.

Veri yapilari:
* ``FieldStat`` — tek bir CalcParams alani icin (float scale) tum projelerdeki
  degerler, median ve outlier flag.
* ``FloorDictStat`` — kat-bazli dict alani icin her kat'in degerleri ayrica
  toplanir; median kat-bazli olarak uretilir.
* ``TrainedProfile`` — kompozit cikti.
"""
from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import yaml

from ..structural.calculator import CalcParams
from ..structural.profile_fitter import (
    _FIT_TARGETS,
    _FLOOR_DICT_TARGETS,
    FitResult,
    dump_fitted_yaml,
    fit_profile_from_dxf,
)

logger = logging.getLogger(__name__)


@dataclass
class FieldStat:
    """Tek bir global scale alani icin proje-bazinda istatistikler."""

    field_name: str
    values: List[float]
    project_names: List[str]
    median: float = 0.0
    mean: float = 0.0
    std: float = 0.0
    q1: float = 0.0
    q3: float = 0.0
    outlier_project_indices: List[int] = field(default_factory=list)

    def finalize(self) -> None:
        if not self.values:
            return
        vals = list(self.values)
        self.median = float(statistics.median(vals))
        self.mean = float(statistics.fmean(vals))
        self.std = float(statistics.pstdev(vals)) if len(vals) > 1 else 0.0
        sorted_vals = sorted(vals)
        n = len(sorted_vals)
        # Quartiles (basit linear interpolation)
        if n >= 4:
            self.q1 = float(sorted_vals[(n - 1) // 4])
            self.q3 = float(sorted_vals[(3 * (n - 1)) // 4])
        else:
            self.q1 = float(sorted_vals[0])
            self.q3 = float(sorted_vals[-1])
        # Tukey outlier fence (sadece n >= 4 anlamli)
        if n >= 4:
            iqr = self.q3 - self.q1
            lo = self.q1 - 1.5 * iqr
            hi = self.q3 + 1.5 * iqr
            for i, v in enumerate(self.values):
                if v < lo or v > hi:
                    self.outlier_project_indices.append(i)


@dataclass
class FloorDictStat:
    """Kat-bazli dict alani icin: her kat etiketi -> proje deger listesi."""

    field_name: str
    per_floor_values: Dict[str, List[Tuple[float, str]]] = field(default_factory=dict)
    per_floor_median: Dict[str, float] = field(default_factory=dict)

    def finalize(self) -> None:
        for floor, pairs in self.per_floor_values.items():
            vals = [v for v, _ in pairs]
            if vals:
                self.per_floor_median[floor] = float(statistics.median(vals))


@dataclass
class TrainedProfile:
    """``train_profiles_from_pairs`` cikisi."""

    project_count: int
    project_names: List[str]
    field_stats: Dict[str, FieldStat] = field(default_factory=dict)
    floor_dict_stats: Dict[str, FloorDictStat] = field(default_factory=dict)
    fitted_params: CalcParams = field(default_factory=CalcParams)
    cross_validation: Optional[Dict[str, Dict[str, float]]] = None
    report: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_count": self.project_count,
            "project_names": list(self.project_names),
            "field_stats": {
                name: {
                    "median": fs.median, "mean": fs.mean, "std": fs.std,
                    "q1": fs.q1, "q3": fs.q3,
                    "values": list(fs.values),
                    "project_names": list(fs.project_names),
                    "outliers": [fs.project_names[i] for i in fs.outlier_project_indices],
                }
                for name, fs in self.field_stats.items()
            },
            "floor_dict_stats": {
                name: {"per_floor_median": dict(fd.per_floor_median)}
                for name, fd in self.floor_dict_stats.items()
            },
            "cross_validation": self.cross_validation,
        }


def _aggregate_field_stats(
    fit_results: Sequence[FitResult],
    project_names: Sequence[str],
) -> Dict[str, FieldStat]:
    """Her global scale alani icin projeler arasi degerleri topla."""
    stats: Dict[str, FieldStat] = {}
    for target in _FIT_TARGETS:
        fs = FieldStat(field_name=target.field_name, values=[], project_names=[])
        for res, name in zip(fit_results, project_names):
            for fr in res.field_results:
                if fr.field_name == target.field_name:
                    fs.values.append(float(fr.fitted_value))
                    fs.project_names.append(name)
                    break
        if fs.values:
            fs.finalize()
            stats[target.field_name] = fs
    return stats


def _aggregate_floor_dict_stats(
    fit_results: Sequence[FitResult],
    project_names: Sequence[str],
) -> Dict[str, FloorDictStat]:
    """Her kat-bazli dict alani icin tum projelerin per-floor scale'lerini bicakla."""
    stats: Dict[str, FloorDictStat] = {}
    for fdt in _FLOOR_DICT_TARGETS:
        fd = FloorDictStat(field_name=fdt.field_name)
        for res, name in zip(fit_results, project_names):
            scales = getattr(res.fitted_params, fdt.field_name, None)
            if not isinstance(scales, Mapping) or not scales:
                continue
            for floor, val in scales.items():
                try:
                    f = float(val)
                except (TypeError, ValueError):
                    continue
                fd.per_floor_values.setdefault(str(floor), []).append((f, name))
        if fd.per_floor_values:
            fd.finalize()
            stats[fdt.field_name] = fd
    return stats


def _build_trained_params(
    field_stats: Mapping[str, FieldStat],
    floor_dict_stats: Mapping[str, FloorDictStat],
) -> CalcParams:
    """Median ile CalcParams olustur."""
    cp = CalcParams()
    for name, fs in field_stats.items():
        if hasattr(cp, name):
            try:
                setattr(cp, name, float(fs.median))
            except Exception:
                logger.warning("CalcParams median set failed: %s -> %s", name, fs.median)
    for name, fd in floor_dict_stats.items():
        if hasattr(cp, name) and fd.per_floor_median:
            try:
                setattr(cp, name, dict(fd.per_floor_median))
            except Exception:
                logger.warning("CalcParams floor-dict median set failed: %s", name)
    return cp


def _build_report(profile: TrainedProfile) -> str:
    lines: List[str] = []
    lines.append("# Multi-Reference Profile Training Raporu")
    lines.append(f"Proje sayisi: {profile.project_count}")
    lines.append(f"Projeler: {', '.join(profile.project_names)}")
    lines.append("")
    lines.append("## Global olcek alanlari (median +/- std)")
    for name, fs in profile.field_stats.items():
        outliers = [fs.project_names[i] for i in fs.outlier_project_indices]
        lines.append(
            f"  - {name}: median={fs.median:.4f}  mean={fs.mean:.4f}  "
            f"std={fs.std:.4f}  IQR=[{fs.q1:.3f},{fs.q3:.3f}]  "
            f"n={len(fs.values)}"
            + (f"  outliers={outliers}" if outliers else "")
        )
    if profile.floor_dict_stats:
        lines.append("")
        lines.append("## Kat-bazli dict alanlari (per-floor median)")
        for name, fd in profile.floor_dict_stats.items():
            lines.append(f"  - {name}:")
            for floor, med in fd.per_floor_median.items():
                vals = [v for v, _ in fd.per_floor_values[floor]]
                lines.append(f"      {floor:10s} median={med:.4f}  n={len(vals)}")
    if profile.cross_validation:
        lines.append("")
        lines.append("## Leave-one-out cross-validation")
        for proj, metrics in profile.cross_validation.items():
            lines.append(
                f"  - {proj}: KALIP sapma={metrics.get('formwork_pct', 0):.2f}%  "
                f"BETON sapma={metrics.get('concrete_pct', 0):.2f}%"
            )
    return "\n".join(lines)


def train_profiles_from_pairs(
    pairs: Sequence[Tuple[str | Path, str | Path]],
    *,
    project_names: Optional[Sequence[str]] = None,
    output_yaml: Optional[str | Path] = None,
    cross_validate: bool = False,
) -> TrainedProfile:
    """N (cad, reference) ciftinden multi-reference profil egitir.

    ``project_names`` verilmezse CAD dosyasi stem'i kullanilir.
    ``cross_validate=True``: her projeyi dislayip kalanin trained profile'i ile
    pipeline kostur; sapma kayitlar (yavas — N x pipeline kosumu).
    """
    if not pairs:
        raise ValueError("train_profiles_from_pairs: bos pair listesi")
    if project_names is None:
        project_names = [Path(c).stem for c, _ in pairs]
    if len(project_names) != len(pairs):
        raise ValueError("project_names sayisi pair sayisina esit degil")

    # 1) Her cift icin profile_fitter cagrisi
    fit_results: List[FitResult] = []
    for (cad, ref), name in zip(pairs, project_names):
        logger.info("Egitim: %s (%s)", name, Path(cad).name)
        res = fit_profile_from_dxf(
            cad_path=cad, reference_excel=ref, output_yaml=None,
            two_stage_fit=True,
        )
        fit_results.append(res)

    # 2) Agrega
    field_stats = _aggregate_field_stats(fit_results, project_names)
    floor_dict_stats = _aggregate_floor_dict_stats(fit_results, project_names)
    trained_params = _build_trained_params(field_stats, floor_dict_stats)

    profile = TrainedProfile(
        project_count=len(pairs),
        project_names=list(project_names),
        field_stats=field_stats,
        floor_dict_stats=floor_dict_stats,
        fitted_params=trained_params,
    )

    # 3) Cross-validation (opsiyonel)
    if cross_validate and len(pairs) >= 2:
        profile.cross_validation = _leave_one_out_validation(
            pairs, project_names, fit_results,
        )

    profile.report = _build_report(profile)

    if output_yaml is not None:
        out_path = Path(output_yaml)
        dump_fitted_yaml(
            trained_params, out_path,
            project_name=f"Trained profile (N={len(pairs)})",
        )

    return profile


def _leave_one_out_validation(
    pairs: Sequence[Tuple[str | Path, str | Path]],
    project_names: Sequence[str],
    fit_results: Sequence[FitResult],
) -> Dict[str, Dict[str, float]]:
    """Her projeyi dislayip kalan N-1'in median CalcParams'i ile koshtur."""
    from ..structural.config import StructuralConfig
    from ..structural.pipeline import StructuralPipeline

    results: Dict[str, Dict[str, float]] = {}
    for i, name in enumerate(project_names):
        # N-1 projenin sonuclari ile trained profile uret
        leave_in_results = [r for j, r in enumerate(fit_results) if j != i]
        leave_in_names = [n for j, n in enumerate(project_names) if j != i]
        if len(leave_in_results) < 1:
            continue
        fs = _aggregate_field_stats(leave_in_results, leave_in_names)
        fds = _aggregate_floor_dict_stats(leave_in_results, leave_in_names)
        trained_cp = _build_trained_params(fs, fds)

        # Test projesini pipeline'a koshtur
        cad, ref = pairs[i]
        cfg = StructuralConfig(
            project_name=f"LOOCV-{name}",
            params=trained_cp,
            reference_excel_path=str(ref),
            excel_layout="kumluca",
            compare_to_reference=True,
            validation_tolerance=0.01,
        )
        pipe = StructuralPipeline(config=cfg)
        res = pipe.run(cad_path=cad, output_dir=f"build/_loocv_{name}",
                       write_excel=False, write_diagnostics=False)

        # Reference'in toplamlarini hesapla
        from ..structural.gt_io import parse_kumluca_reference
        ref_rep = parse_kumluca_reference(Path(ref))
        ref_form = sum(r.total for r in ref_rep.formwork_rows)
        ref_conc = sum(r.total for r in ref_rep.concrete_rows)
        f_pct = abs(res.report.formwork_total_m2 - ref_form) / max(abs(ref_form), 1e-9) * 100
        c_pct = abs(res.report.concrete_total_m3 - ref_conc) / max(abs(ref_conc), 1e-9) * 100
        results[name] = {
            "formwork_pct": float(f_pct),
            "concrete_pct": float(c_pct),
        }
        logger.info("LOOCV %s: KALIP=%.2f%% BETON=%.2f%%", name, f_pct, c_pct)
    return results


# ---------------------------------------------------------------------------
# Mock fit-result yardımcısı (test ve sentetik senaryolar icin)
# ---------------------------------------------------------------------------


def build_trained_profile_from_fit_results(
    fit_results: Sequence[FitResult],
    project_names: Sequence[str],
) -> TrainedProfile:
    """Halihazirda hesaplanmis FitResult listesinden TrainedProfile uretir.

    train_profiles_from_pairs'in pahali (pipeline kosma) yan etkilerini atlayip
    sadece aggregation mantigini test etmek icin kullanilir.
    """
    field_stats = _aggregate_field_stats(fit_results, project_names)
    floor_dict_stats = _aggregate_floor_dict_stats(fit_results, project_names)
    trained_params = _build_trained_params(field_stats, floor_dict_stats)
    profile = TrainedProfile(
        project_count=len(fit_results),
        project_names=list(project_names),
        field_stats=field_stats,
        floor_dict_stats=floor_dict_stats,
        fitted_params=trained_params,
    )
    profile.report = _build_report(profile)
    return profile


__all__ = [
    "FieldStat",
    "FloorDictStat",
    "TrainedProfile",
    "train_profiles_from_pairs",
    "build_trained_profile_from_fit_results",
]
