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


def _cmd_structural_feedback(args: argparse.Namespace) -> int:
    """Faz 5: proje-bazli FeedbackStore JSON uzerinde CRUD + global hint cikari."""
    from metraj.core.learning.feedback_store import (
        FeedbackStore,
        extract_global_hints,
        global_hints_to_signal_hints_yaml,
        load_stores_from_dir,
    )
    import yaml as _yaml

    sub_action = args.action

    if sub_action == "list":
        store = FeedbackStore.load(args.store)
        print(f"Proje: {store.project_name or '(belirsiz)'}")
        print(f"Kaynak: {store.source_path}")
        print()
        print(f"layer_kind_overrides ({len(store.layer_kind_overrides)}):")
        for k, v in sorted(store.layer_kind_overrides.items()):
            print(f"  {k:30s} -> {v}")
        print(f"comparison_alias_overrides ({len(store.comparison_alias_overrides)}):")
        for k, v in sorted(store.comparison_alias_overrides.items()):
            print(f"  {k:30s} -> {v}")
        print(f"excluded_layers ({len(store.excluded_layers)}): {store.excluded_layers}")
        print(f"manual_classifications ({len(store.manual_classifications)}):")
        for mc in store.manual_classifications:
            print(f"  layer={mc.layer:20s} centroid={mc.centroid} -> {mc.kind} ({mc.reason})")
        if store.notes:
            print(f"notes ({len(store.notes)}):")
            for n in store.notes:
                print(f"  - {n}")
        return 0

    if sub_action == "set-layer-kind":
        store = FeedbackStore.load(args.store)
        store.set_layer_kind(args.layer, args.kind)
        if args.project_name and not store.project_name:
            store.project_name = args.project_name
        store.save(args.store)
        print(f"[ok] {args.layer!r} -> {args.kind!r} eklendi: {args.store}")
        return 0

    if sub_action == "remove-layer-kind":
        store = FeedbackStore.load(args.store)
        removed = store.remove_layer_kind(args.layer)
        store.save(args.store)
        print(f"[{'ok' if removed else 'noop'}] {args.layer!r}: {args.store}")
        return 0

    if sub_action == "set-alias":
        store = FeedbackStore.load(args.store)
        store.set_alias(args.src, args.dst)
        store.save(args.store)
        print(f"[ok] alias {args.src!r} -> {args.dst!r}: {args.store}")
        return 0

    if sub_action == "exclude-layer":
        store = FeedbackStore.load(args.store)
        store.exclude_layer(args.layer)
        store.save(args.store)
        print(f"[ok] exclude {args.layer!r}: {args.store}")
        return 0

    if sub_action == "global-hints":
        stores = load_stores_from_dir(args.feedback_dir)
        if not stores:
            print(f"HATA: feedback dosyasi yok: {args.feedback_dir}", file=sys.stderr)
            return 2
        hints = extract_global_hints(stores, min_project_count=args.min_projects)
        print(f"{len(stores)} projeden {len(hints)} global hint cikarildi.")
        for h in hints:
            print(f"  [{h.kind}] {h.source!r} -> {h.target!r}  "
                  f"(projeler={h.project_count}: {', '.join(h.projects)})")
        if args.output:
            payload = global_hints_to_signal_hints_yaml(hints)
            Path(args.output).parent.mkdir(parents=True, exist_ok=True)
            with open(args.output, "w", encoding="utf-8") as fh:
                fh.write("# Otomatik cikarilmis global signal_hints (Faz 5)\n\n")
                _yaml.safe_dump(payload, fh, allow_unicode=True, sort_keys=False)
            print(f"\nsignal_hints YAML yazildi: {args.output}")
        return 0

    print(f"HATA: bilinmeyen alt-komut: {sub_action}", file=sys.stderr)
    return 2


def _cmd_wizard(args: argparse.Namespace) -> int:
    """Kalibrasyon sihirbazini ac (PySide6 QDialog)."""
    try:
        from metraj.app.calibration_wizard import launch_wizard
    except Exception as exc:
        print(f"HATA: calibration_wizard import basarisiz: {exc}", file=sys.stderr)
        return 2
    cad = Path(args.cad) if args.cad else None
    ref = Path(args.reference) if args.reference else None
    out = Path(args.output) if args.output else None
    try:
        return launch_wizard(cad=cad, ref=ref, output=out)
    except RuntimeError as exc:
        print(f"HATA: {exc}", file=sys.stderr)
        return 2


def _cmd_config_wizard(args: argparse.Namespace) -> int:
    """Excel-bagimsiz config sihirbazi: kullanici UI'da CalcParams ayarlar.

    Kullanim:
      metraj config-wizard -o profile.yaml [--preset geometry_full]
    Sonrasinda:
      metraj run --mode structural --structural-config profile.yaml <cad>
    """
    from metraj.app.structural_config_dialog import (
        calcparams_to_yaml,
        launch_config_dialog,
        list_method_presets,
        load_method_preset,
    )

    if args.list_presets:
        presets = list_method_presets()
        print(f"Mevcut presetler ({len(presets)}):")
        for p in presets:
            print(f"  {p}")
        return 0

    # GUI'siz preset dump modu
    if args.preset_only:
        try:
            cp = load_method_preset(args.preset)
        except FileNotFoundError as exc:
            print(f"HATA: {exc}", file=sys.stderr)
            return 2
        out = Path(args.output)
        calcparams_to_yaml(cp, out, project_name=f"Preset: {args.preset}")
        print(f"Preset YAML kaydedildi: {out.resolve()}")
        return 0

    # GUI dialog
    out = Path(args.output) if args.output else Path("profile.yaml")
    try:
        return launch_config_dialog(preset=args.preset, output=out)
    except RuntimeError as exc:
        print(f"HATA: {exc}", file=sys.stderr)
        print("\nGUI'siz preset kaydetmek icin --preset-only kullanin:",
              file=sys.stderr)
        print("  metraj config-wizard --preset geometry_full --preset-only "
              "-o profile.yaml", file=sys.stderr)
        return 2


def _cmd_train_profiles(args: argparse.Namespace) -> int:
    """Faz 6: N (cad, reference) ciftinden median trained profile uretir."""
    from metraj.core.learning.profile_trainer import train_profiles_from_pairs

    pairs: list[tuple[Path, Path]] = []
    for raw in args.pairs:
        parts = raw.split(",", 1)
        if len(parts) != 2:
            print(f"HATA: --pairs format: cad,ref (verilen: {raw!r})",
                  file=sys.stderr)
            return 2
        cad_p = Path(parts[0].strip())
        ref_p = Path(parts[1].strip())
        if not cad_p.is_file():
            print(f"HATA: CAD bulunamadi: {cad_p}", file=sys.stderr)
            return 2
        if not ref_p.is_file():
            print(f"HATA: Reference bulunamadi: {ref_p}", file=sys.stderr)
            return 2
        pairs.append((cad_p, ref_p))

    project_names = args.names.split(",") if args.names else None

    print(f"{len(pairs)} (CAD, Excel) cifti egitiliyor...")
    profile = train_profiles_from_pairs(
        pairs=pairs,
        project_names=project_names,
        output_yaml=args.output,
        cross_validate=args.cross_validate,
    )
    print()
    print(profile.report)
    print()
    print(f"Trained profile YAML: {args.output}")
    return 0


def _cmd_structural_fit(args: argparse.Namespace) -> int:
    """Faz 4: CAD + referans Excel'den CalcParams profili otomatik fit eder."""
    from metraj.core.structural.config import StructuralConfig
    from metraj.core.structural.profile_fitter import fit_profile_from_dxf

    cad = Path(args.cad)
    ref = Path(args.reference)
    out_yaml = Path(args.output)

    if not cad.is_file():
        print(f"HATA: CAD bulunamadi: {cad}", file=sys.stderr)
        return 2
    if not ref.is_file():
        print(f"HATA: Referans Excel bulunamadi: {ref}", file=sys.stderr)
        return 2

    base_cfg = None
    if args.base_config:
        base_cfg = StructuralConfig.from_file(args.base_config)

    print(f"CAD: {cad.resolve()}")
    print(f"Referans: {ref.resolve()}")
    print(f"Cikti YAML: {out_yaml.resolve()}")
    print()
    print("Saf geometri pipeline'i kosturuluyor (baseline)...")
    result = fit_profile_from_dxf(
        cad_path=cad,
        reference_excel=ref,
        output_yaml=out_yaml,
        base_config=base_cfg,
    )
    print()
    print(result.report)
    print()
    print(f"Profil YAML yazildi: {result.yaml_path}")
    print("Sonraki adim: `metraj run --mode structural --structural-config "
          f"{out_yaml} <cad>`")
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

    sfb = sub.add_parser(
        "structural-feedback",
        help="Faz 5: proje feedback JSON store uzerinde CRUD + global hint cikari",
    )
    sfb_sub = sfb.add_subparsers(dest="action", required=True)

    sfb_list = sfb_sub.add_parser("list", help="Store'daki tum overrideleri listele")
    sfb_list.add_argument("store", help="Feedback JSON yolu")
    sfb_list.set_defaults(func=_cmd_structural_feedback)

    sfb_set = sfb_sub.add_parser("set-layer-kind",
                                  help="Katman icin ElementKind override ekle")
    sfb_set.add_argument("store")
    sfb_set.add_argument("layer", help="DXF katman adi")
    sfb_set.add_argument("kind", help="ElementKind (column/shear_wall/beam/slab/...)")
    sfb_set.add_argument("--project-name", default=None)
    sfb_set.set_defaults(func=_cmd_structural_feedback)

    sfb_rm = sfb_sub.add_parser("remove-layer-kind",
                                 help="Katman override'ini kaldir")
    sfb_rm.add_argument("store")
    sfb_rm.add_argument("layer")
    sfb_rm.set_defaults(func=_cmd_structural_feedback)

    sfb_al = sfb_sub.add_parser("set-alias",
                                 help="Comparison alias ekle (gt_io.comparison_key)")
    sfb_al.add_argument("store")
    sfb_al.add_argument("src", help="Kaynak etiket")
    sfb_al.add_argument("dst", help="Hedef etiket")
    sfb_al.set_defaults(func=_cmd_structural_feedback)

    sfb_ex = sfb_sub.add_parser("exclude-layer",
                                 help="Katmani extractor'dan disla")
    sfb_ex.add_argument("store")
    sfb_ex.add_argument("layer")
    sfb_ex.set_defaults(func=_cmd_structural_feedback)

    sfb_gh = sfb_sub.add_parser("global-hints",
                                 help="Birden fazla projedeki ortak override'lari signal_hints YAML olarak cikar")
    sfb_gh.add_argument("feedback_dir", help="*.json feedback dosyalarinin oldugu klasor")
    sfb_gh.add_argument("--min-projects", type=int, default=2,
                        help="Bir override global olmak icin minimum proje sayisi")
    sfb_gh.add_argument("-o", "--output", default=None,
                        help="Cikti signal_hints YAML (verilmezse sadece stdout)")
    sfb_gh.set_defaults(func=_cmd_structural_feedback)

    wz = sub.add_parser(
        "wizard",
        help="Kalibrasyon sihirbazini ac (PySide6 GUI; Faz 4 profile fitter sarmal)",
    )
    wz.add_argument("--cad", default=None, help="On-set CAD yolu")
    wz.add_argument("--reference", default=None, help="On-set referans Excel yolu")
    wz.add_argument("-o", "--output", default=None, help="On-set cikti YAML yolu")
    wz.set_defaults(func=_cmd_wizard)

    cw = sub.add_parser(
        "config-wizard",
        help="Excel-bagimsiz config sihirbazi: UI uzerinden CalcParams ayarla "
             "(Saf geometri / yari kesit / ozel)",
    )
    cw.add_argument(
        "-o", "--output", default="profile.yaml",
        help="Cikti YAML yolu (varsayilan: profile.yaml)",
    )
    cw.add_argument(
        "--preset", default="geometry_full",
        help="Baslangic preset: geometry_full / geometry_half / custom_template",
    )
    cw.add_argument(
        "--preset-only", action="store_true",
        help="GUI'siz: sadece preset'i YAML olarak yaz (PySide6 gerektirmez)",
    )
    cw.add_argument(
        "--list-presets", action="store_true",
        help="Mevcut presetleri listele ve cik",
    )
    cw.set_defaults(func=_cmd_config_wizard)

    tp = sub.add_parser(
        "train-profiles",
        help="Faz 6: N (cad, reference) ciftinden median trained profile uretir",
    )
    tp.add_argument(
        "--pairs", action="append", required=True, metavar="CAD,REF",
        help="(virgulle ayrilmis) CAD ve referans Excel cifti; tekrarlanabilir",
    )
    tp.add_argument(
        "--names", default=None,
        help="(virgulle ayrilmis) proje isimleri; verilmezse CAD stem'i kullanilir",
    )
    tp.add_argument(
        "-o", "--output", default="trained_profile.yaml",
        help="Cikti trained profile YAML",
    )
    tp.add_argument(
        "--cross-validate", action="store_true",
        help="Leave-one-out cross-validation (yavas; her proje icin pipeline kosumu)",
    )
    tp.set_defaults(func=_cmd_train_profiles)

    sfit = sub.add_parser(
        "structural-fit",
        help="DXF + referans Excel'den CalcParams profili otomatik fit eder (Faz 4)",
    )
    sfit.add_argument("cad", help="DWG/DXF dosyasi (yapisal cizim)")
    sfit.add_argument("reference", help="Referans Excel (Kumluca formatinda)")
    sfit.add_argument(
        "-o", "--output", default="profile.yaml",
        help="Cikti YAML yolu (varsayilan: profile.yaml)",
    )
    sfit.add_argument(
        "--base-config", default=None, metavar="YAML",
        help="Layer overrideleri + signal_hints icin baz config (params fit edilir).",
    )
    sfit.set_defaults(func=_cmd_structural_fit)

    ui = sub.add_parser("ui", help="PySide6 grafiksel arayuzu baslat (ana pencere)")
    ui.add_argument(
        "--config", default="metraj/config",
        help="Mimari config klasoru (varsayilan: metraj/config)",
    )
    ui.set_defaults(func=_cmd_ui)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _setup_logging(args.verbose)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
