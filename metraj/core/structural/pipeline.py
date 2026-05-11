"""Yapisal (kaba insaat) metraj pipeline orkestrasyonu."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from ..cad_io.converter import DwgConverter
from ..cad_io.dxf_reader import DxfReader, RawCadModel, inventory_layers
from .calculator import StructuralReport, calculate
from .classify import (
    ClassificationConflict,
    GeometricThresholds,
    deduplicate_overlapping_beams,
    find_classification_conflicts,
    remove_collinear_centroids,
    union_slabs_per_plan,
)
from .config import StructuralConfig, default_config
from .diagnostics import write_diagnostics_json
from .elements import StructuralElement, StructuralModel
from .excel_writer import write_kumluca_reference_layout, write_structural_xlsx
from .extractor import (
    collapse_overlapping,
    containment_dedupe,
    deduplicate,
    extract_structural_elements,
    filter_by_plan,
    hash_dedupe_by_geometry,
)
from .floor_segmenter import (
    FloorAssignment,
    assign_elements_to_plans,
    attach_floor_labels,
    detect_plan_groups,
)
from .layer_detection import (
    StructuralLayerReport,
    apply_structural_layer_overrides,
    detect_structural_layers,
)
from .layer_signals import collect_layer_signals
from .gt_io import (
    ValidationRowDetail,
    compare_reports_full,
    merge_comparison_aliases,
    parse_kumluca_reference,
    snap_report_to_reference,
)
from .plan_labels import PlanLabelLocale, detect_plan_multipliers, detect_title_anchors

logger = logging.getLogger(__name__)


@dataclass
class ValidationCompareSummary:
    """UI/dogrulama dosyasi icin hesap vs referans ozeti."""

    reference_path: Path
    tolerance: float
    max_rel_error_formwork: float
    max_rel_error_concrete: float
    row_details: List[ValidationRowDetail]
    warning_lines: List[str]


@dataclass
class StructuralPipelineResult:
    smodel: StructuralModel
    report: StructuralReport
    layer_report_kind_to_layers: dict
    excel_path: Optional[Path] = None
    plan_count: int = 0
    notes: List[str] = field(default_factory=list)
    #: Faz 0 teshis JSON'u (eleman bazinda kind/layer/bbox/aspect_ratio); benchmark
    #: ve gelecek (Faz 1) siniflandirici icin ortak girdi.
    diagnostics_path: Optional[Path] = None
    #: Faz 3: layer-bazli ve geometric_classify uyusmazliklari ("kuskulu siniflandirma").
    #: Sessiz overwrite YAPILMAZ; element.kind layer-bazli kalir, UI bunlari listeler.
    classification_conflicts: List["ClassificationConflict"] = field(default_factory=list)
    #: ``compare_to_reference`` aciksa yazilan metin dosyasi (uyari listesi).
    validation_summary_path: Optional[Path] = None
    #: Satir bazinda hesap vs referans (UI tablosu).
    validation_detail: Optional[ValidationCompareSummary] = None
    #: Autodetect (override oncesi) katman raporu — UI icin.
    layer_report_autodetect: Optional[StructuralLayerReport] = None
    #: Manuel dahil/hariç sonrasi kullanilan rapor.
    layer_report_effective: Optional[StructuralLayerReport] = None
    #: CAD kaynak katman listesi (sirali).
    source_layers: List[str] = field(default_factory=list)


class StructuralPipeline:
    def __init__(self, config: Optional[StructuralConfig] = None) -> None:
        self.config = config or default_config()
        self.dwg_converter = DwgConverter()
        self.dxf_reader = DxfReader(
            explode_inserts=getattr(self.config, "explode_inserts", False),
        )

    def run(
        self,
        cad_path: str | Path,
        output_dir: str | Path = "build/structural",
        write_excel: bool = True,
        write_diagnostics: bool = True,
    ) -> StructuralPipelineResult:
        cad_path = Path(cad_path)
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # 1) DWG/DXF -> RawCadModel
        dxf_path = self.dwg_converter.ensure_dxf(cad_path)
        model = self.dxf_reader.read(dxf_path)
        logger.info(
            "Yapisal pipeline: %d katman, %d polyline, %d hatch",
            len(model.layers), len(model.polylines), len(model.hatches),
        )

        # 2) Yapisal autodetect + kullanici katman overrideleri
        inv = inventory_layers(model)
        # Faz 1: signal_hints YAML/inline + entity istatistikleri ile skor sistemi.
        # Verilmediyse score_layer cagrilmaz, eski regex davranisi calisir.
        signal_hints = self.config.load_signal_hints() if hasattr(self.config, "load_signal_hints") else {}
        layer_sigs = collect_layer_signals(model) if signal_hints else None
        layer_report_ad = detect_structural_layers(
            model.layers, layer_inventory=inv,
            layer_signals=layer_sigs,
            layer_colors=model.layer_colors or None,
            signal_hints=signal_hints or None,
        )
        inc = dict(getattr(self.config, "structural_layer_include_kind", None) or {})
        exc = list(getattr(self.config, "structural_layer_exclude", None) or [])
        alias_merge = dict(getattr(self.config, "comparison_label_aliases", None) or {})
        # Faz 5: feedback_store override'larini merge et
        fb_path = getattr(self.config, "feedback_store_path", None)
        if fb_path:
            try:
                from ..learning.feedback_store import FeedbackStore
                fb = FeedbackStore.load(fb_path)
                fb.apply_to_config_dicts(inc, alias_merge, exc)
                if fb.notes:
                    logger.info("FeedbackStore notlari (%s): %s",
                                fb.source_path, "; ".join(fb.notes[:3]))
            except Exception as e:
                logger.warning("feedback_store yuklenemedi (%s): %s", fb_path, e)
        layer_report = apply_structural_layer_overrides(
            layer_report_ad,
            include_kind=inc,
            exclude_layers=exc,
        )
        always_keep = set(inc.keys())

        # 3) Eleman cikarimi
        raw_elements, _ = extract_structural_elements(
            model,
            layer_report=layer_report,
            layer_always_keep=always_keep or None,
            include_standalone_lines=getattr(self.config, "include_standalone_lines", False),
        )
        logger.info("Ham eleman: %d", len(raw_elements))
        # 3a) Hash bazli hizli dedupe (centroid+alan) — DWG'de plan kopyalari
        # nedeniyle ayni polygonun bircok kopyasi var
        elements = hash_dedupe_by_geometry(raw_elements,
                                           centroid_round_m=0.20,
                                           area_round_pct=0.05)
        # 3b) Centroid bazli ek temizlik
        elements = remove_collinear_centroids(elements, tol_m=0.05)
        # 3c) Detayli dedupe (centroid + alan + IoU)
        # Toleranslar genis: aynı kolonun dis konturu + ic tarama sinirinda
        # alan farki %20-30 olabilir.
        elements = deduplicate(elements, iou_threshold=0.5,
                               centroid_tol_m=0.30, area_tol_pct=0.50)
        # 3d) Ic-ice cizimleri at (kolon dis kontur + ic tarama sinir gibi)
        elements = containment_dedupe(elements)
        # 3e) Reklasifikasyon yok — kategori atamasi calculate()'de plan-bazli

        # 4) Plan kumelemesi
        # Faz 2: locale yukle (dil-agnostik plan basligi parser'i)
        locale_obj = None
        if self.config.plan_labels_locale:
            try:
                locale_obj = PlanLabelLocale.load(self.config.plan_labels_locale)
            except Exception as e:
                logger.warning("plan_labels_locale yuklenemedi (%s): %s",
                               self.config.plan_labels_locale, e)
        plan_axis = (self.config.plan_cluster_axis or "x").lower()
        if plan_axis not in {"x", "y", "auto"}:
            plan_axis = "x"
        # Once DWG'deki plan basliklarindan x merkezleri cikar (en guvenilir).
        # Anchor-bazli optimize yol simdilik sadece yatay layout icin aktiftir;
        # axis='y' veya 'auto' icin detect_plan_groups fallback'ine duser.
        anchors_all = detect_title_anchors(
            model.texts,
            storey_h=self.config.params.typical_storey_height_m,
            locale=locale_obj,
        )
        # Anchor'lari yapisal polygon X aralığında olanlarla sinirla (hesap
        # tablosu/cerceve metinleri plandan cok uzak X'lerde olabilir).
        if elements:
            x_centroids = []
            for el in elements:
                try:
                    x_centroids.append(el.geom.centroid.x)
                except Exception:
                    continue
            if x_centroids:
                x_min_p = min(x_centroids) - 5.0
                x_max_p = max(x_centroids) + 5.0
                anchors = [(x, info) for (x, info) in anchors_all
                           if x_min_p <= x <= x_max_p]
            else:
                anchors = anchors_all
        else:
            anchors = anchors_all
        logger.info("Anchor metni: %d (toplam %d, polygon araligindaki)",
                    len(anchors), len(anchors_all))
        if plan_axis == "x" and len(anchors) >= 2:
            # Anchor'lara gore plan'lari Voronoi-style olustur: ardisik anchor
            # ortasi sinir
            anchor_xs = [a[0] for a in anchors]
            anchor_xs_sorted = sorted(anchor_xs)
            boundaries = [
                (anchor_xs_sorted[i] + anchor_xs_sorted[i+1]) / 2
                for i in range(len(anchor_xs_sorted) - 1)
            ]
            # Her anchor icin x_min..x_max aralik (sol-sag sinir)
            cluster_xs = []
            prev = float("-inf")
            for i, ax in enumerate(anchor_xs_sorted):
                next_b = boundaries[i] if i < len(boundaries) else float("inf")
                cluster_xs.append((prev, next_b))
                prev = next_b
            # Her cluster icin polygon centroid'lerinden bbox cikar
            plans: List[FloorAssignment] = []
            for x_lo, x_hi in cluster_xs:
                pts = []
                for el in elements:
                    try:
                        c = el.geom.centroid
                        if x_lo <= c.x < x_hi:
                            pts.append(el.geom)
                    except Exception:
                        continue
                if not pts:
                    continue
                bounds = [p.bounds for p in pts]
                bbox = (
                    min(b[0] for b in bounds),
                    min(b[1] for b in bounds),
                    max(b[2] for b in bounds),
                    max(b[3] for b in bounds),
                )
                plans.append(FloorAssignment(bbox=bbox))
            logger.info(
                "Anchor tabanli plan kumeleme: %d anchor -> %d plan",
                len(anchors), len(plans),
            )
        else:
            plans = detect_plan_groups(
                elements,
                expected_floor_count=self.config.expected_floor_count,
                axis=plan_axis,
            )
            attach_floor_labels(plans, model.texts, floor_label_layers=self.config.floor_label_layers)

        # 5) Plan etiketlerini DWG metinlerinden once set et (anchor-based
        # plan kumelemeden farkli labellandi, calculate icin temel)
        # Once FloorAssignment'lara etiket koymamiz lazim — anchor sirasi
        # gercek plan etiketlerinden.  Anchor varsa kullan.
        if anchors:
            for plan, (_, info) in zip(plans, [(a, b) for a, b in anchors]):
                plan.label = info.canonical_label
                plan.elevation_m = info.elevation_m

        # 5a) Eleman -> kat ataması (artik plan label'lari set edilmis)
        # axis="auto" calistirildiysa detect_plan_groups secimi pipeline'da bilinmiyor;
        # bu durumda "x" varsayilan; auto secim sadece detect_plan_groups icinde
        # bbox sirasini etkiler — element ataması bbox tabanli oldugu icin tutarli.
        assign_axis = "x" if plan_axis == "auto" else plan_axis
        floor_plans, unassigned = assign_elements_to_plans(
            elements, plans, config_floors=None,
            typical_storey_height_m=self.config.params.typical_storey_height_m,
            axis=assign_axis,
        )

        # 5b) Plan basligi metinlerinden multiplier ve nihai etiket
        # (anchor'dan gelen etiket cogu zaman dogru, multi-kat bilgisi de
        # buradan gelir)
        detect_plan_multipliers(floor_plans, model.texts,
                                storey_h=self.config.params.typical_storey_height_m,
                                locale=locale_obj)

        # Plan label degisikliginden sonra eleman floor_label'larini guncelle
        for fp in floor_plans:
            for el in fp.elements:
                el.floor_label = fp.label

        # 5c) Plan-baglami filtreleri:
        #     - TEMEL planinda kiris/doseme/parapet beklemiyoruz
        #       (yapilan ciziminde varsa muhtemelen baska planin kalintisi)
        #     - Cati/asansor kule planinda kolon olmaz
        plan_kinds_allowed = {
            "TEMEL": {"foundation", "lean_concrete", "column", "shear_wall",
                      "stair", "elevator_shaft", "chimney", "protection"},
        }
        for fp in floor_plans:
            kept = filter_by_plan(fp.elements, plan_kinds_allowed=plan_kinds_allowed)
            dropped = len(fp.elements) - len(kept)
            if dropped > 0:
                logger.info("Plan '%s' filtresi: %d eleman atildi", fp.label, dropped)
            fp.elements = kept

        # 5d) Foundation/grobeton gibi parcali cizilen elemanlari birlestir
        for fp in floor_plans:
            collapsed = collapse_overlapping([
                e for e in fp.elements
                if e.kind in ("foundation", "lean_concrete")
            ], overlap_iou=0.3)
            others = [e for e in fp.elements
                      if e.kind not in ("foundation", "lean_concrete")]
            fp.elements = others + collapsed

        # 5e) Plan basina DOSEME polygonlarini union et (ayni katta birden cok
        # buyuk doseme varsa birlestir; kucukler asansor/teras olarak ayri kalir)
        for fp in floor_plans:
            fp.elements = union_slabs_per_plan(
                fp.elements, main_slab_min_area_m2=50.0,
            )
            fp.elements = deduplicate_overlapping_beams(fp.elements, iou_threshold=0.35)

        smodel = StructuralModel(floors=floor_plans, unassigned=unassigned)

        # Faz 3: hibrit siniflandirma kontrolu — sessiz overwrite YOK, sadece uyari.
        classification_conflicts: List[ClassificationConflict] = []
        if getattr(self.config, "classification_conflict_check", True):
            th = GeometricThresholds.from_dict(
                getattr(self.config, "geometric_thresholds", None),
            )
            classification_conflicts = find_classification_conflicts(
                smodel.all_elements(), thresholds=th,
            )
            if classification_conflicts:
                logger.info(
                    "Hibrit siniflandirma: %d eleman icin layer-bazli ile "
                    "geometri-bazli kind farkli (kuskulu).",
                    len(classification_conflicts),
                )

        # 6) Hesap
        report = calculate(smodel, self.config.params)

        # Faz 5: alias_merge zaten config + feedback_store override'larini icerir.
        cmp_aliases = merge_comparison_aliases(
            getattr(self.config, "excel_layout", "generic"),
            alias_merge,
        )
        strip_labels_list = getattr(self.config, "strip_kot_prefix_labels", None) or []
        strip_labels_fs: Optional[frozenset[str]] = (
            frozenset(strip_labels_list) if strip_labels_list else None
        )

        refp: Optional[Path] = None
        if self.config.reference_excel_path:
            cand = Path(self.config.reference_excel_path)
            if not cand.is_file():
                alt = Path.cwd() / self.config.reference_excel_path
                cand = alt if alt.is_file() else cand
            if cand.is_file():
                refp = cand

        if self.config.snap_rows_to_reference:
            if refp is not None:
                report = snap_report_to_reference(
                    report, refp, comparison_aliases=cmp_aliases,
                    excel_layout=getattr(self.config, "excel_layout", "generic"),
                    strip_prefix_labels=strip_labels_fs,
                )
            else:
                logger.warning(
                    "snap_rows_to_reference acik ama referans bulunamadi: %s",
                    self.config.reference_excel_path,
                )

        validation_summary_path: Optional[Path] = None
        validation_detail: Optional[ValidationCompareSummary] = None
        if (
            getattr(self.config, "compare_to_reference", False)
            and refp is not None
        ):
            tol = float(getattr(self.config, "validation_tolerance", 0.01))
            ref_rep = parse_kumluca_reference(refp)
            warnings, max_k, max_b, rows = compare_reports_full(
                report, ref_rep, rtol=tol,
                comparison_aliases=cmp_aliases,
                excel_layout=getattr(self.config, "excel_layout", "generic"),
                strip_prefix_labels=strip_labels_fs,
            )
            validation_detail = ValidationCompareSummary(
                reference_path=refp.resolve(),
                tolerance=tol,
                max_rel_error_formwork=max_k,
                max_rel_error_concrete=max_b,
                row_details=rows,
                warning_lines=list(warnings),
            )
            report.notes.append(
                "Dogrulama (referans Excel; cikti DWG hesabidir): "
                f"{refp.name} — KALIP max rel sapma {max_k * 100:.2f}%, "
                f"BETON max rel sapma {max_b * 100:.2f}%; "
                f"{len(warnings)} satir esik ustu (>{tol * 100:.1f}%) veya "
                "referansta olup hesapta olmayan etiket."
            )
            lines = [
                f"Referans: {refp}",
                f"Esik (rtol): {tol}",
                f"KALIP max rel sapma: {max_k * 100:.4f}%",
                f"BETON max rel sapma: {max_b * 100:.4f}%",
                f"Uyari satiri: {len(warnings)}",
                "",
            ]
            lines.extend(warnings)
            validation_summary_path = output_dir / "dogrulama_ozeti.txt"
            validation_summary_path.write_text(
                "\n".join(lines), encoding="utf-8",
            )
        elif getattr(self.config, "compare_to_reference", False):
            logger.warning(
                "compare_to_reference acik ama referans bulunamadi: %s",
                self.config.reference_excel_path,
            )

        # 7) Excel + diagnostics JSON (Faz 0)
        excel_path = None
        if write_excel:
            excel_path = output_dir / "yapisal_metraj.xlsx"
            layout = getattr(self.config, "excel_layout", "generic")
            if layout == "kumluca":
                write_kumluca_reference_layout(
                    report, excel_path, project_name=self.config.project_name,
                )
            else:
                write_structural_xlsx(report, excel_path, project_name=self.config.project_name)

        diagnostics_path: Optional[Path] = None
        if write_diagnostics:
            diagnostics_path = write_diagnostics_json(
                smodel, output_dir / "elements_diagnostics.json",
            )

        return StructuralPipelineResult(
            smodel=smodel,
            report=report,
            layer_report_kind_to_layers=layer_report.kind_to_layers,
            excel_path=excel_path,
            plan_count=len(floor_plans),
            notes=report.notes,
            diagnostics_path=diagnostics_path,
            classification_conflicts=classification_conflicts,
            validation_summary_path=validation_summary_path,
            validation_detail=validation_detail,
            layer_report_autodetect=layer_report_ad,
            layer_report_effective=layer_report,
            source_layers=sorted(model.layers),
        )


def detect_drawing_kind(model: RawCadModel) -> str:
    """DWG'nin mimari mi yapisal mi olduguna karar verir.

    Heuristik:
      1) Mimari sinyal = MAHAL/ROOM/ODA LEJANT etiket katmanlarinda *gercek
         metin* sayisi (text adedi).
      2) Yapisal sinyal = KOLON/KIRIS/PERDE/DOSEME NA katmanlarinda kapali
         polyline sayisi.
      3) Yapisal yogunluk mimariden buyukse ve mimari yok denecek kadar
         azsa 'structural' donulur; aksi durumda 'architectural'.

    Bu, mimari + yapisal birlikte ataşman olan DWG'lerde de dogru
    tarafa karar vermeyi mumkun kilar.
    """
    arch_text_count = 0
    arch_keys = ("MAHAL", "ROOM", "ODA LEJANT", "ODA NO", "AREA-IDEN", "ETIKET")
    struct_keys_strong = ("KOLON NA", "KİRİŞ NA", "KIRIS NA", "PERDE NA",
                          "DÖŞEME NA", "DOSEME NA", "GROBETON NA",
                          "BETONARME_KOLON", "BETONARME_PERDE")

    for t in model.texts:
        u = t.layer.upper()
        if any(k in u for k in arch_keys):
            arch_text_count += 1

    struct_poly_count = 0
    for poly in model.polylines:
        u = poly.layer.upper()
        if any(k in u for k in struct_keys_strong) and poly.closed:
            struct_poly_count += 1

    # Yapisal cogunluk: 100+ kapali polygon + arch text 200'den az -> yapisal
    # (Kumluca: 700+ struct polygon, 0 arch text)
    if struct_poly_count >= 50 and struct_poly_count > arch_text_count:
        return "structural"
    if arch_text_count >= 50:
        return "architectural"
    if struct_poly_count >= 20:
        return "structural"
    return "architectural"  # default
