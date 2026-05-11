"""Saf geometri vs kalibre profil sapma kiyaslamasi (Faz 0 baz cizgi).

Bir CAD dosyasi + bir kalibre YAML profili verir. Pipeline'i iki kez calistirir:

1. **Kalibre profil**: YAML icindeki ``params`` (CalcParams) aynen kullanilir.
2. **Saf geometri**: Ayni config (referans Excel, layout, kat listesi) ama
   ``params`` varsayilan ``CalcParams()`` (tum carpanlar 1.0) ile sifirlanir.

Cikti:
* ``benchmark.csv`` — iki kosumun toplam ve max sapma rakamlari (her satir bir kosum).
* ``benchmark.md`` — okuma kolay Markdown tablo.

Sonraki fazlar (Faz 1-6) ayni kalibre/saf farkini bu CSV'ye satir ekleyerek
trend olarak izleyecek; hedef: saf sapmanin kalibre sapmaya yakinsayasi.

Ornek kullanim:

.. code-block:: bash

   python -m metraj.benchmarks.bench_geometry_vs_reference \\
       --cad "1828-14 MIMARI PROJE 15.04.2022 REVIZYON.dxf" \\
       --profile metraj/config/references/kumluca.yaml \\
       --output build/bench_phase0
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from ..core.structural.calculator import CalcParams
from ..core.structural.config import StructuralConfig
from ..core.structural.gt_io import (
    compare_reports_full,
    merge_comparison_aliases,
    parse_kumluca_reference,
)
from ..core.structural.pipeline import StructuralPipeline


@dataclass
class BenchRow:
    """Tek pipeline kosumunun ozeti."""

    label: str
    project_name: str
    cad_path: str
    reference_path: Optional[str]
    formwork_total_m2: float
    concrete_total_m3: float
    formwork_max_rel_err: Optional[float]
    concrete_max_rel_err: Optional[float]
    warnings_count: Optional[int]
    elapsed_s: float


def _run_pipeline(
    cad_path: Path,
    config: StructuralConfig,
    out_dir: Path,
    label: str,
) -> tuple[BenchRow, object]:
    """Pipeline'i bir kez calistirir; benchmark ozetini ve report'u doner."""
    t0 = time.time()
    pipe = StructuralPipeline(config=config)
    run_dir = out_dir / label
    run_dir.mkdir(parents=True, exist_ok=True)
    res = pipe.run(cad_path=cad_path, output_dir=run_dir, write_excel=True)
    elapsed = time.time() - t0

    max_k: Optional[float] = None
    max_b: Optional[float] = None
    warns: Optional[int] = None

    # Eger kalibre profil ise pipeline kendi dogrulamasini yapar.
    if res.validation_detail is not None:
        max_k = float(res.validation_detail.max_rel_error_formwork)
        max_b = float(res.validation_detail.max_rel_error_concrete)
        warns = len(res.validation_detail.warning_lines)
    elif config.reference_excel_path:
        # Saf geometri kosumunda compare_to_reference kapali olsa bile
        # benchmark icin manuel kiyaslama yapariz.
        ref_path = Path(config.reference_excel_path)
        if ref_path.is_file():
            ref_rep = parse_kumluca_reference(ref_path)
            aliases = merge_comparison_aliases(
                config.excel_layout, config.comparison_label_aliases,
            )
            strip_fs = (
                frozenset(config.strip_kot_prefix_labels)
                if config.strip_kot_prefix_labels else None
            )
            warnings_, k, b, _ = compare_reports_full(
                res.report, ref_rep,
                rtol=config.validation_tolerance,
                comparison_aliases=aliases,
                excel_layout=config.excel_layout,
                strip_prefix_labels=strip_fs,
            )
            max_k, max_b, warns = float(k), float(b), len(warnings_)

    row = BenchRow(
        label=label,
        project_name=config.project_name,
        cad_path=str(cad_path),
        reference_path=str(config.reference_excel_path) if config.reference_excel_path else None,
        formwork_total_m2=float(res.report.formwork_total_m2),
        concrete_total_m3=float(res.report.concrete_total_m3),
        formwork_max_rel_err=max_k,
        concrete_max_rel_err=max_b,
        warnings_count=warns,
        elapsed_s=elapsed,
    )
    return row, res.report


def _make_geometry_only_config(base: StructuralConfig) -> StructuralConfig:
    """Kalibre config'in geometrik aynisi (params=CalcParams varsayilan)."""
    geom = StructuralConfig(
        project_name=base.project_name + " [saf geometri]",
        floors=list(base.floors),
        params=CalcParams(
            storey_heights={f.label: f.storey_height_m for f in base.floors}
            if base.floors else {},
        ),
        expected_floor_count=base.expected_floor_count,
        floor_label_layers=list(base.floor_label_layers),
        reference_excel_path=base.reference_excel_path,
        excel_layout=base.excel_layout,
        snap_rows_to_reference=False,
        compare_to_reference=False,
        validation_tolerance=base.validation_tolerance,
        comparison_label_aliases=dict(base.comparison_label_aliases),
        strip_kot_prefix_labels=list(base.strip_kot_prefix_labels),
        structural_layer_include_kind=dict(base.structural_layer_include_kind),
        structural_layer_exclude=list(base.structural_layer_exclude),
    )
    return geom


def write_csv(rows: List[BenchRow], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow([
            "label", "project_name", "cad_path", "reference_path",
            "formwork_total_m2", "concrete_total_m3",
            "formwork_max_rel_err_pct", "concrete_max_rel_err_pct",
            "warnings_count", "elapsed_s",
        ])
        for r in rows:
            w.writerow([
                r.label, r.project_name, r.cad_path, r.reference_path or "",
                f"{r.formwork_total_m2:.4f}",
                f"{r.concrete_total_m3:.4f}",
                f"{r.formwork_max_rel_err * 100:.4f}" if r.formwork_max_rel_err is not None else "",
                f"{r.concrete_max_rel_err * 100:.4f}" if r.concrete_max_rel_err is not None else "",
                r.warnings_count if r.warnings_count is not None else "",
                f"{r.elapsed_s:.2f}",
            ])


def write_markdown(rows: List[BenchRow], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: List[str] = []
    lines.append("# Metraj Benchmark — Saf Geometri vs Kalibre Profil")
    lines.append("")
    lines.append("Faz 0 baz cizgi: ayni CAD dosyasi iki farkli config ile calistirilir.")
    lines.append("Hedef (gelecek fazlarda): saf sapma kalibre sapmaya yakinsasin.")
    lines.append("")
    lines.append("| Kosum | Proje | KALIP toplam (m2) | BETON toplam (m3) | KALIP max sapma | BETON max sapma | Uyari | Sure (s) |")
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|")
    for r in rows:
        fk = f"{r.formwork_max_rel_err * 100:.2f}%" if r.formwork_max_rel_err is not None else "—"
        bk = f"{r.concrete_max_rel_err * 100:.2f}%" if r.concrete_max_rel_err is not None else "—"
        wc = str(r.warnings_count) if r.warnings_count is not None else "—"
        lines.append(
            f"| {r.label} | {r.project_name} | "
            f"{r.formwork_total_m2:.2f} | {r.concrete_total_m3:.2f} | "
            f"{fk} | {bk} | {wc} | {r.elapsed_s:.1f} |"
        )
    lines.append("")
    lines.append("## Cikti yollari")
    for r in rows:
        lines.append(f"* `{r.label}/yapisal_metraj.xlsx`, `{r.label}/elements_diagnostics.json`")
    lines.append("")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--cad", required=True, help="DWG veya DXF dosyasi")
    parser.add_argument("--profile", required=True, help="Kalibre YAML (ornek: kumluca.yaml)")
    parser.add_argument("--output", required=True, help="Cikti klasoru")
    parser.add_argument("--skip-geometry-only", action="store_true",
                        help="Sadece kalibre kosumu yap (geometri-only atlanir)")
    args = parser.parse_args(argv)

    cad_path = Path(args.cad).resolve()
    profile_path = Path(args.profile).resolve()
    out_dir = Path(args.output).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    if not cad_path.is_file():
        print(f"HATA: CAD dosyasi bulunamadi: {cad_path}", file=sys.stderr)
        return 2
    if not profile_path.is_file():
        print(f"HATA: profil YAML bulunamadi: {profile_path}", file=sys.stderr)
        return 2

    print(f"[bench] Kalibre profil yukleniyor: {profile_path.name}")
    calibrated = StructuralConfig.from_file(profile_path)

    rows: List[BenchRow] = []

    print(f"[bench] Kosum 1/2: kalibre profil ({calibrated.project_name})")
    row_calib, _rep_calib = _run_pipeline(
        cad_path=cad_path, config=calibrated, out_dir=out_dir, label="calibrated",
    )
    rows.append(row_calib)

    if not args.skip_geometry_only:
        print("[bench] Kosum 2/2: saf geometri (CalcParams=varsayilan)")
        geom_only = _make_geometry_only_config(calibrated)
        row_geom, _rep_geom = _run_pipeline(
            cad_path=cad_path, config=geom_only, out_dir=out_dir, label="geometry_only",
        )
        rows.append(row_geom)

    csv_path = out_dir / "benchmark.csv"
    md_path = out_dir / "benchmark.md"
    write_csv(rows, csv_path)
    write_markdown(rows, md_path)

    print()
    print(f"[bench] CSV : {csv_path}")
    print(f"[bench] MD  : {md_path}")
    print()
    print(json.dumps([{
        "label": r.label,
        "formwork_total_m2": r.formwork_total_m2,
        "concrete_total_m3": r.concrete_total_m3,
        "formwork_max_rel_err": r.formwork_max_rel_err,
        "concrete_max_rel_err": r.concrete_max_rel_err,
        "warnings_count": r.warnings_count,
    } for r in rows], ensure_ascii=False, indent=2))

    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
