"""Command-line entry point.

Usage examples
--------------

Yeni proje icin konfigurasyon klasoru olustur:

    python -m metraj.cli new-project ./projeler/yeni_proje

Faz 0 envanteri + otomatik katman tespiti:

    python -m metraj.cli inventory data/samples/foo.dxf --autodetect-layers

Tam pipeline (proje konfigurasyonu ile):

    python -m metraj.cli run --config ./projeler/yeni_proje proje.dxf -o build/

GUI (PySide6):

    python -m metraj.cli ui
"""
from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
from pathlib import Path
from typing import Optional, Sequence

import yaml

from .core.cad_io import DwgConverter, DxfReader, OdaNotFoundError
from .core.cad_io.converter import diagnose_dwg_support
from .core.cad_io.dxf_reader import inventory_blocks, inventory_layers
from .core.excel.ground_truth import GroundTruthReader
from .core.mapping import autodetect_layer_map, merge_into_layer_map
from .pipeline import Pipeline, PipelineConfig

PACKAGE_DIR = Path(__file__).resolve().parent
CONFIG_DIR = PACKAGE_DIR / "config"
TEMPLATES_DIR = CONFIG_DIR / "templates"


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


def _cmd_inventory(args: argparse.Namespace) -> int:
    converter = DwgConverter(binary_path=args.oda)
    try:
        dxf_path = converter.ensure_dxf(args.cad)
    except OdaNotFoundError as exc:
        print(f"HATA: {exc}", file=sys.stderr)
        return 2
    model = DxfReader(target_unit="m").read(dxf_path)
    layers = inventory_layers(model)
    blocks = inventory_blocks(model)
    payload = {
        "source": str(dxf_path),
        "units": model.units,
        "layer_count": len(model.layers),
        "block_definition_count": len(model.block_definitions),
        "layer_inventory": layers,
        "top_blocks": dict(sorted(blocks.items(), key=lambda kv: kv[1], reverse=True)[:50]),
        "totals": {
            "lines": len(model.lines),
            "polylines": len(model.polylines),
            "texts": len(model.texts),
            "blocks": len(model.blocks),
            "hatches": len(model.hatches),
        },
    }
    if args.autodetect_layers:
        report = autodetect_layer_map(model)
        payload["autodetect"] = {
            "role_to_layers": report.role_to_layers,
            "unmatched_layers": report.unmatched,
            "layer_to_role": report.proposed_map,
        }
        if args.write_layer_map:
            merged = merge_into_layer_map(report)
            out_path = Path(args.write_layer_map)
            merged.to_yaml(out_path)
            payload["autodetect"]["written_to"] = str(out_path)
    if args.json:
        out = Path(args.json)
        out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Envanter raporu yazildi: {out}")
    else:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


def _cmd_new_project(args: argparse.Namespace) -> int:
    target = Path(args.path).resolve()
    if target.exists() and any(target.iterdir()) and not args.force:
        print(f"HATA: {target} bos degil. --force ile uzerine yaz.", file=sys.stderr)
        return 1
    target.mkdir(parents=True, exist_ok=True)
    src = TEMPLATES_DIR
    if not src.exists():
        print(f"HATA: Sablon dizini bulunamadi: {src}", file=sys.stderr)
        return 1
    for filename in ("layer_map.yaml", "poz_library.yaml",
                     "tip_definitions.yaml", "project.yaml"):
        s = src / filename
        d = target / filename
        if s.exists():
            shutil.copy2(s, d)
    if args.proje_adi:
        proje_yaml = target / "project.yaml"
        data = yaml.safe_load(proje_yaml.read_text(encoding="utf-8")) or {}
        data["proje_adi"] = args.proje_adi
        proje_yaml.write_text(
            yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
    print(f"Yeni proje konfigurasyonu olusturuldu: {target}")
    print(f"Sonraki adim:")
    print(f"  1) python -m metraj.cli inventory --autodetect-layers \\")
    print(f"        --write-layer-map {target / 'layer_map.yaml'} <DWG/DXF>")
    print(f"  2) {target}/tip_definitions.yaml dosyasini firma standardiniza gore")
    print(f"     duzenleyin (D1, W1, T1 ... yerine kendi tip kodlariniz).")
    print(f"  3) python -m metraj.cli run --config {target} <DWG/DXF> -o build/")
    return 0


def _detect_drawing_kind_for_path(cad_path: str, oda_binary: Optional[str]) -> str:
    """DWG/DXF'i hizlica okuyup mimari mi yapisal mi karar ver."""
    from .core.structural.pipeline import detect_drawing_kind
    converter = DwgConverter(binary_path=oda_binary)
    dxf_path = converter.ensure_dxf(cad_path)
    model = DxfReader(target_unit="m").read(dxf_path)
    return detect_drawing_kind(model)


def _cmd_run(args: argparse.Namespace) -> int:
    mode = args.mode
    if mode == "auto":
        try:
            mode = _detect_drawing_kind_for_path(args.cad, args.oda)
            print(f"[mod=auto] Cizim tipi: {mode}")
        except OdaNotFoundError as exc:
            print(f"HATA: {exc}", file=sys.stderr)
            return 2
        except Exception as exc:
            logging.exception("Mod tespiti basarisiz, mimari moduna geciliyor")
            mode = "architectural"

    if mode == "structural":
        return _cmd_run_structural(args)

    config = PipelineConfig.from_directory(args.config)
    pipeline = Pipeline(config)
    try:
        result = pipeline.run(
            cad_path=args.cad,
            output_dir=args.output,
            excel_name=args.excel,
            pdf_name=args.pdf,
            oda_binary=args.oda,
            write_excel=not args.no_excel,
            write_pdf=not args.no_pdf,
            autodetect_layers=not args.no_autodetect,
        )
    except Exception as exc:
        logging.exception("Pipeline hatasi")
        print(f"HATA: {exc}", file=sys.stderr)
        return 1
    print(f"Mahal sayisi      : {len(result.rooms)}")
    print(f"Acikliklar        : {len(result.openings)}")
    print(f"Duvar segmentleri : {len(result.walls)}")
    print(f"Icmal poz sayisi  : {len(result.icmal.rows)}")
    print(f"Genel toplam (TL) : {result.icmal.grand_total:,.2f}")
    if len(result.rooms) == 0:
        print()
        print("UYARI: Hicbir mahal tespit edilemedi.")
        print("  Bu cizim yapisal/kaba insaat plani gibi gorunuyor.")
        print("  Yapisal metraj icin: 'metraj run --mode structural ...' veya")
        print("  '--mode auto' deneyebilirsiniz.")
    if result.autodetect_report and result.autodetect_report.unmatched:
        print(f"Autodetect: {len(result.autodetect_report.unmatched)} eslesmeyen "
              f"katman (ilk 5: {', '.join(result.autodetect_report.unmatched[:5])})")
    if result.config_gaps and result.config_gaps.has_gaps():
        print("Konfig boslugu:")
        for line in result.config_gaps.summary().splitlines():
            print(f"  {line}")
    if result.excel_path:
        print(f"Excel: {result.excel_path}")
    if result.pdf_path:
        print(f"PDF  : {result.pdf_path}")
    return 0


def _cmd_run_structural(args: argparse.Namespace) -> int:
    """Yapisal (kaba insaat) pipeline."""
    from .core.structural import StructuralConfig, StructuralPipeline, default_config

    if args.structural_config:
        scfg = StructuralConfig.from_file(args.structural_config)
    else:
        scfg = default_config()
    pipeline = StructuralPipeline(scfg)
    try:
        result = pipeline.run(
            cad_path=args.cad,
            output_dir=args.output,
            write_excel=not args.no_excel,
        )
    except OdaNotFoundError as exc:
        print(f"HATA: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        logging.exception("Yapisal pipeline hatasi")
        print(f"HATA: {exc}", file=sys.stderr)
        return 1
    rep = result.report
    print(f"[mod=structural] {scfg.project_name}")
    print(f"Plan kumesi sayisi : {result.plan_count}")
    el_count = len(result.smodel.all_elements())
    print(f"Yapisal eleman     : {el_count}")
    by_kind = {}
    for el in result.smodel.all_elements():
        by_kind[el.kind] = by_kind.get(el.kind, 0) + 1
    if by_kind:
        kinds_str = ", ".join(f"{k}={v}" for k, v in sorted(by_kind.items()))
        print(f"  ({kinds_str})")
    print(f"Kalip toplami      : {rep.formwork_total_m2:>10.2f} m2")
    print(f"Beton toplami      : {rep.concrete_total_m3:>10.2f} m3")
    print()
    print("Kat bazli ozet:")
    floor_kalip = {}
    floor_beton = {}
    for r in rep.formwork_rows:
        floor_kalip[r.floor_label or "?"] = floor_kalip.get(r.floor_label or "?", 0) + r.total
    for r in rep.concrete_rows:
        floor_beton[r.floor_label or "?"] = floor_beton.get(r.floor_label or "?", 0) + r.total
    all_floors = sorted(set(list(floor_kalip.keys()) + list(floor_beton.keys())))
    for fl in all_floors:
        print(f"  {fl:<10s} kalip={floor_kalip.get(fl, 0):>9.2f} m2  "
              f"beton={floor_beton.get(fl, 0):>9.2f} m3")
    if result.excel_path:
        print(f"\nExcel: {result.excel_path}")
    return 0


def _cmd_structural_compare(args: argparse.Namespace) -> int:
    """Ayni CAD ile birden fazla yapisal YAML kos; GT dogrulama metriklerini kiyasla."""
    from metraj.core.structural import StructuralConfig, StructuralPipeline

    cad = Path(args.cad)
    out_base = Path(args.output)
    out_base.mkdir(parents=True, exist_ok=True)

    print(f"CAD: {cad.resolve()}")
    print(f"Cikti tabani: {out_base.resolve()}")
    print()

    rows: list[dict] = []
    for i, cfg_path in enumerate(args.config):
        cfg_path = Path(cfg_path)
        sub_out = out_base / f"{i:02d}_{cfg_path.stem}"
        scfg = StructuralConfig.from_file(cfg_path)
        pipeline = StructuralPipeline(scfg)
        try:
            result = pipeline.run(
                cad_path=cad,
                output_dir=sub_out,
                write_excel=not args.no_excel,
            )
        except Exception as exc:
            logging.exception("structural-compare kosusu basarisiz")
            print(f"HATA [{cfg_path}]: {exc}", file=sys.stderr)
            return 1

        vd = result.validation_detail
        rows.append(
            {
                "cfg": str(cfg_path),
                "out": str(sub_out),
                "kalip_m2": result.report.formwork_total_m2,
                "beton_m3": result.report.concrete_total_m3,
                "max_k_pct": (vd.max_rel_error_formwork * 100.0) if vd else None,
                "max_b_pct": (vd.max_rel_error_concrete * 100.0) if vd else None,
                "warnings": len(vd.warning_lines) if vd else None,
                "summary": result.validation_summary_path,
            }
        )

    w_cfg = max(len(r["cfg"]) for r in rows)
    hdr = (
        f"{'Konfig':<{w_cfg}}  Kalip(m2)   Beton(m3)   K_max%%   B_max%%   "
        f"Uyari  dogrulama_ozeti"
    )
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        mk = f"{r['max_k_pct']:.4f}" if r["max_k_pct"] is not None else "—"
        mb = f"{r['max_b_pct']:.4f}" if r["max_b_pct"] is not None else "—"
        nw = str(r["warnings"]) if r["warnings"] is not None else "—"
        summ = str(r["summary"]) if r["summary"] else "—"
        print(
            f"{r['cfg']:<{w_cfg}}  {r['kalip_m2']:>9.2f}  {r['beton_m3']:>9.2f}  "
            f"{mk:>8}  {mb:>8}  {nw:>5}  {summ}"
        )

    if len(rows) >= 2:
        k0 = rows[0]["kalip_m2"]
        b0 = rows[0]["beton_m3"]
        same_totals = all(
            abs(r["kalip_m2"] - k0) < 1e-4 and abs(r["beton_m3"] - b0) < 1e-4
            for r in rows
        )
        if same_totals:
            print()
            print(
                "Not: Tum kosular ayni kalip/beton toplamina sahip — YAML olcekleri "
                "eslesiyorsa GT dogrulama satirlari da ayni olmalidir."
            )
    return 0


def _cmd_compare(args: argparse.Namespace) -> int:
    """Compare a generated metraj output against the firma's ground-truth Excel."""
    config = PipelineConfig.from_directory(args.config)
    pipeline = Pipeline(config)
    try:
        result = pipeline.run(
            cad_path=args.cad,
            output_dir=args.output,
            oda_binary=args.oda,
            write_excel=False,
            write_pdf=False,
        )
    except Exception as exc:
        logging.exception("Pipeline hatasi")
        print(f"HATA: {exc}", file=sys.stderr)
        return 1
    gt = GroundTruthReader().read(args.ground_truth)
    gt_rooms = gt.by_code()
    matched = 0
    diffs = []
    for q in result.quantities:
        ref = gt_rooms.get(q.room.code)
        if not ref:
            continue
        matched += 1
        diff_pct = 0.0
        if ref.area > 0:
            diff_pct = (q.room.area - ref.area) / ref.area * 100.0
        diffs.append((q.room.code, ref.area, q.room.area, diff_pct))
    diffs.sort(key=lambda d: abs(d[3]), reverse=True)
    print(f"Eslesen mahal: {matched} / {len(result.quantities)}")
    print("Buyukten kucuge (%) ilk 20 sapma:")
    for code, ref_area, area, pct in diffs[:20]:
        print(f"  {code:<10s} ref={ref_area:8.2f} m2  yeni={area:8.2f} m2  fark={pct:+.2f}%")
    return 0


def _cmd_ui(args: argparse.Namespace) -> int:
    try:
        from .app.main_window import launch
    except ImportError as exc:
        print(f"PySide6 yuklu degil: {exc}\n  pip install --user PySide6", file=sys.stderr)
        return 2
    return launch(config_dir=Path(args.config))


def _cmd_docs(args: argparse.Namespace) -> int:
    from .scripts.build_user_guide import build
    out = build(Path(args.output))
    print(f"Kullanim klavuzu olusturuldu: {out.resolve()}")
    return 0


def _cmd_diagnose(args: argparse.Namespace) -> int:
    info = diagnose_dwg_support()
    print("=== Sistem DWG destek durumu ===")
    print(f"Platform        : {info['platform']} {info['platform_release']}")
    print(f"ODA bulundu     : {'EVET' if info['oda_available'] else 'HAYIR'}")
    if info["oda_available"]:
        print(f"ODA yolu        : {info['oda_path']}")
        print()
        print("Sistem hazir. DWG dosyalari ile dogrudan calisabilirsiniz.")
        return 0
    print(f"Aranilan yollar : {', '.join(info['searched_paths'])}")
    print()
    print(info["install_help"])
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Metraj: AutoCAD tabanli mimari metraj otomasyonu",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument(
        "--config",
        default=str(CONFIG_DIR),
        help=f"Config klasoru (varsayilan: {CONFIG_DIR})",
    )
    parser.add_argument("--oda", default=None, help="ODA File Converter ikilisinin yolu")
    sub = parser.add_subparsers(dest="cmd", required=True)

    inv = sub.add_parser("inventory", help="DXF/DWG katman ve blok envanteri")
    inv.add_argument("cad", help="DWG/DXF dosyasi")
    inv.add_argument("--json", default=None, help="JSON ciktisini bu yola yaz")
    inv.add_argument("--autodetect-layers", action="store_true",
                     help="Katman isimlerinden role'leri otomatik tahmin et")
    inv.add_argument("--write-layer-map", default=None,
                     help="Tahmin edilen LayerMap'i bu YAML yoluna kaydet")
    inv.set_defaults(func=_cmd_inventory)

    run = sub.add_parser("run", help="Tam pipeline: mahal + minha + icmal (mimari) "
                                       "veya kalip+beton (yapisal)")
    run.add_argument("cad", help="DWG/DXF dosyasi")
    run.add_argument("-o", "--output", default="build", help="Cikti klasoru")
    run.add_argument("--excel", default="metraj.xlsx")
    run.add_argument("--pdf", default="metraj.pdf")
    run.add_argument("--no-excel", action="store_true")
    run.add_argument("--no-pdf", action="store_true")
    run.add_argument("--no-autodetect", action="store_true",
                     help="Katman heuristik tespitini devre disi birak")
    run.add_argument(
        "--mode",
        choices=("architectural", "structural", "auto"),
        default="auto",
        help="architectural=mahal/kapi/pencere/duvar, structural=kolon/kiris/perde/doseme, "
             "auto=cizim icindeki katmanlara bakarak otomatik sec (varsayilan)",
    )
    run.add_argument(
        "--structural-config",
        default=None,
        help="Yapisal mod icin YAML konfig dosyasi yolu (kat kotlari, "
             "beton kalitesi vs.). Bos birakilirsa jenerik 7 katli sablon kullanilir.",
    )
    run.set_defaults(func=_cmd_run)

    np = sub.add_parser("new-project",
                        help="Yeni proje icin konfig klasoru olustur (sablonlardan)")
    np.add_argument("path", help="Olusturulacak klasor (orn. ./projeler/yeni)")
    np.add_argument("--proje-adi", default=None,
                    help="project.yaml icindeki proje_adi alanini ayarla")
    np.add_argument("--force", action="store_true", help="Klasor bos degilse uzerine yaz")
    np.set_defaults(func=_cmd_new_project)

    docs = sub.add_parser("docs", help="Kullanim klavuzunu PDF olarak uret")
    docs.add_argument("-o", "--output", default="docs/Metraj_Kullanim_Klavuzu.pdf",
                      help="Cikti PDF dosyasi (varsayilan: docs/Metraj_Kullanim_Klavuzu.pdf)")
    docs.set_defaults(func=_cmd_docs)

    diag = sub.add_parser("diagnose",
                          help="Sistemde DWG dönüştürme imkanlari raporu (ODA durumu)")
    diag.set_defaults(func=_cmd_diagnose)

    cmp_ = sub.add_parser("compare", help="Mevcut Excel ile karsilastir (Faz 0 PoC dogrulamasi)")
    cmp_.add_argument("cad", help="DWG/DXF dosyasi")
    cmp_.add_argument("ground_truth", help="Mevcut Excel mahal kitabi")
    cmp_.add_argument("-o", "--output", default="build")
    cmp_.set_defaults(func=_cmd_compare)

    scmp = sub.add_parser(
        "structural-compare",
        help="Ayni CAD'i birden fazla yapisal YAML ile kos; dogrulama ozetini kiyasla",
    )
    scmp.add_argument("cad", help="DWG/DXF dosyasi")
    scmp.add_argument(
        "--config",
        dest="config",
        action="append",
        required=True,
        metavar="YAML",
        help="Yapisal YAML (tekrarlanabilir; sirayla kosulur)",
    )
    scmp.add_argument(
        "-o",
        "--output",
        default="build/structural_compare",
        help="Her kosu icin alt klasor (varsayilan: build/structural_compare)",
    )
    scmp.add_argument("--no-excel", action="store_true")
    scmp.set_defaults(func=_cmd_structural_compare)

    ui = sub.add_parser("ui", help="PySide6 grafiksel arayuzu baslat")
    ui.set_defaults(func=_cmd_ui)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _setup_logging(args.verbose)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
