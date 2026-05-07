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
    deduplicate_overlapping_beams,
    remove_collinear_centroids,
    union_slabs_per_plan,
)
from .config import StructuralConfig, default_config
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
from .gt_io import (
    ValidationRowDetail,
    compare_reports_full,
    merge_comparison_aliases,
    parse_kumluca_reference,
    snap_report_to_reference,
)
from .plan_labels import detect_plan_multipliers, detect_title_anchors

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
        self.dxf_reader = DxfReader()

    def run(
        self,
        cad_path: str | Path,
        output_dir: str | Path = "build/structural",
        write_excel: bool = True,
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
        layer_report_ad = detect_structural_layers(model.layers, layer_inventory=inv)
        inc = dict(getattr(self.config, "structural_layer_include_kind", None) or {})
        exc = list(getattr(self.config, "structural_layer_exclude", None) or [])
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
        # Once DWG'deki plan basliklarindan x merkezleri cikar (en guvenilir).
        anchors_all = detect_title_anchors(
            model.texts,
            storey_h=self.config.params.typical_storey_height_m,
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
        if len(anchors) >= 2:
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
        floor_plans, unassigned = assign_elements_to_plans(
            elements, plans, config_floors=None,
            typical_storey_height_m=self.config.params.typical_storey_height_m,
        )

        # 5b) Plan basligi metinlerinden multiplier ve nihai etiket
        # (anchor'dan gelen etiket cogu zaman dogru, multi-kat bilgisi de
        # buradan gelir)
        detect_plan_multipliers(floor_plans, model.texts,
                                storey_h=self.config.params.typical_storey_height_m)

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

        # 6) Hesap
        report = calculate(smodel, self.config.params)

        cmp_aliases = merge_comparison_aliases(
            getattr(self.config, "excel_layout", "generic"),
            getattr(self.config, "comparison_label_aliases", None),
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

        # 7) Excel
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

        return StructuralPipelineResult(
            smodel=smodel,
            report=report,
            layer_report_kind_to_layers=layer_report.kind_to_layers,
            excel_path=excel_path,
            plan_count=len(floor_plans),
            notes=report.notes,
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
