"""Yapisal kalip m^2 ve beton m^3 hesabi.

Kumluca ground truth'una bakarak hesap formulleri:

* TEMEL kalip      = perimetre * derinlik   (yan yuzeyler)
* TEMEL beton      = alan * derinlik
* GROBETON kalip   = alan (sadece zemin koruyucu kalip)
* KOLON kalip      = (perimetre * column_formwork_strip_fraction) * h_storey
* KOLON beton      = alan * column_concrete_section_fraction * h_storey
* PERDE kalip      = perimetre * h_storey   (perde poligonu kapali alan
                     icerdiginden cevrenin tamami zaten iki yuze karsilik
                     gelir)
* KIRIS kalip      = uzunluk * (kiris_derinligi)   (taban + 1 yan, diger
                     yan komsu doseme/kirisle paylasimli sayilir)
* DOSEME kalip     = alan
* DOSEME YAN kalip = perimetre * doseme_kalinligi
* DOSEME beton     = alan * doseme_kalinligi
* BOSLUK MINHA     = bosluk_alani * (kalip 1, beton kalinlikla); alan/cevre
                     slab_net_area_fraction ile doseme ile ayni olceklenir
* BOSLUK YAN KALIP = bosluk_perimetresi * doseme_kalinligi (aynı carpan)
* PARAPET kalip    = uzunluk * yukseklik (iki yuz icin x2)
* PARAPET beton    = alan * kalinlik

Sonuc 'A KALIP' ve 'A BETON' icmal listesi formatinda satirlardir.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Mapping, Optional

from shapely.geometry import MultiPolygon, Polygon
from shapely.ops import unary_union

from .elements import FloorPlan, StructuralElement, StructuralModel

logger = logging.getLogger(__name__)


@dataclass
class CalcParams:
    typical_storey_height_m: float = 2.85
    #: Kolon kalip satirinda qty1 (etkin kalip uzunlugu): tam cevre * bu carpandir.
    #: Kumluca referans Excel ile uyum icin 0.5 (iki yuz / etkin serit); genel 1.0.
    column_formwork_strip_fraction: float = 1.0
    #: Kolon beton kesit alani (m2) ile carpilir — Kumluca GT kesit toplami ile uyum icin 0.5.
    column_concrete_section_fraction: float = 1.0
    #: Perde beton kesit alani carpani (TEMEL ve diger perde beton satirlari).
    shear_wall_concrete_section_fraction: float = 1.0
    #: Radye temel beton kesit alani (GT ile bilesik / cift cizim uyumu).
    foundation_concrete_section_fraction: float = 1.0
    #: Kiris kalip: uzunluk x derinlik; GT ile uyum icin uzunluk carpanı.
    beam_formwork_length_fraction: float = 1.0
    #: Kiris beton kesit alani (polygon alani x derinlik).
    beam_concrete_section_fraction: float = 1.0
    #: Zemin (0,00) kiris betonu — Excel'de kesit benzeri miktar (qty1) ust katlardan dusuk
    #: olabilir (or. tek kot geometrisi); varsayilan 1 (degistirmeden).
    beam_zemin_concrete_qty_scale: float = 1.0
    #: Kat etiketi -> kiriş kalıp satırı ek çarpanı (projeye özel GT hizası).
    beam_formwork_floor_scale: Dict[str, float] = field(default_factory=dict)
    #: Kat etiketi -> kiriş beton satırı ek çarpanı.
    beam_concrete_floor_scale: Dict[str, float] = field(default_factory=dict)
    #: Son tipik kat planında kirişler GT'de ``12,00`` ve ``15,00`` (CATI) diye ikiye ayrilir;
    #: DWG tek planda ve CATI'de kiriş çizgisi yoksa ham toplam burada bölünür.
    beam_split_source_floor_label: str = ""
    beam_split_roof_floor_label: str = "CATI"
    beam_split_roof_fraction: float = 0.0
    beam_split_adjust_formwork: float = 1.0
    beam_split_adjust_concrete: float = 1.0
    #: ``+11,40`` planinda kiris birlesim minha GT'de 12,00 ve 15,00 diye ikiye ayrilir.
    beam_split_join_minha_roof_fraction: float = 0.0
    beam_split_adjust_join_minha: float = 1.0
    #: Kiris birlesim minha (kalip): kat etiketi -> GT satiri ile carpim (bos sozluk = 1).
    beam_join_minha_floor_scale: Dict[str, float] = field(default_factory=dict)
    #: Doseme net alani carpanı (DOSEME kalip + doseme beton satirlari).
    slab_net_area_fraction: float = 1.0
    #: Bodrum TEMEL kalip + GROBETON kalip perimetre carpanı (Kumluca GT ~ yarim serit).
    foundation_plan_formwork_scale: float = 1.0
    #: Parapet beton hacmi carpani (GT kesit farki).
    parapet_concrete_volume_fraction: float = 1.0
    #: TEMEL / GROBETON kalip satirlari referans Excel ile mikro hizalama.
    temel_gt_scale: float = 1.0
    grobeton_formwork_gt_scale: float = 1.0
    #: Kat etiketi -> doseme net alan ve bosluk satirlari (aynı geometri, GT fark).
    doseme_net_scale_by_floor_label: Dict[str, float] = field(default_factory=dict)
    #: Beton ``DOSEME`` satiri icin ayri carpan (GT kalip alani ile beton tutarliligi farkli olabilir).
    doseme_concrete_net_scale_by_floor_label: Dict[str, float] = field(default_factory=dict)
    kolon_head_minha_floor_scale: Dict[str, float] = field(default_factory=dict)
    #: Tum katlarda KOLON YERLERI MINHA (GT tek blok / kiyaslama anahtari).
    kolon_head_minha_scale: float = 1.0
    slab_opening_concrete_scale: float = 1.0
    parapet_formwork_floor_scale: Dict[str, float] = field(default_factory=dict)
    foundation_depth_m: float = 0.5
    lean_concrete_thickness_m: float = 0.10
    roof_protection_thickness_m: float = 0.05
    roof_slab_thickness_m: float = 0.10
    slab_thickness_m: float = 0.15
    beam_depth_m: float = 0.45      # kiris derinligi (kalip)
    beam_width_m: float = 0.25      # kiris genisligi (alt yuz icin)
    beam_join_minha_m: float = 0.135  # kiris birlesim noktalarinda dusen
    beam_height_m: float = 0.45
    parapet_thickness_m: float = 0.20
    concrete_grade: str = "C35"
    # Kullanici verirse, kat etiketi -> ozel yukseklik
    storey_heights: Dict[str, float] = field(default_factory=dict)
    # Asansor kule ve baca yukseklikleri ortalama (kat sayisi*h_storey)
    elevator_extra_height_m: float = 1.45
    #: GT bazen tek satirda tek şaft gösterir; DWG'de ayni kottta birden fazla poligon
    #: varsa carp ile uyum (varsayilan 1 = geometrik toplam).
    elevator_shaft_quantity_scale: float = 1.0
    chimney_height_m: float = 0.9


@dataclass
class CalcRow:
    category: str        # "KOLON", "PERDE", "DOSEME", "MINHA", ...
    label: str           # "0,00 KOLON", "DÖŞEME BOŞLUK MİNHA"
    floor_label: Optional[str]
    qty1: float          # uzunluk veya cevre veya alan
    qty1_unit: str       # "m", "m2"
    qty2: float          # yukseklik / kalinlik / derinlik
    qty2_unit: str       # "m"
    total: float         # m2 veya m3
    total_unit: str      # "m2" veya "m3"
    sign: int = 1        # +1 ya da -1 (minha)


@dataclass
class StructuralReport:
    formwork_rows: List[CalcRow] = field(default_factory=list)  # KALIP
    concrete_rows: List[CalcRow] = field(default_factory=list)  # BETON
    formwork_total_m2: float = 0.0
    concrete_total_m3: float = 0.0
    by_floor_summary: Dict[str, Dict[str, float]] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)


def _add_form(rep: StructuralReport, **kwargs):
    rep.formwork_rows.append(CalcRow(
        total_unit="m2", qty1_unit=kwargs.pop("qty1_unit", "m"), qty2_unit="m",
        **kwargs,
    ))


def _add_conc(rep: StructuralReport, **kwargs):
    rep.concrete_rows.append(CalcRow(
        total_unit="m3", qty1_unit=kwargs.pop("qty1_unit", "m2"), qty2_unit="m",
        **kwargs,
    ))


def _dedupe_vertical_shafts_by_centroid(
    floors_sorted: List[FloorPlan],
    kind: str,
    *,
    is_temel_plan,
    grid_m: float = 0.12,
) -> tuple[List[StructuralElement], str]:
    """Ayni merkezde tekrarlanan asansor/baca poligonlarini tek say (coklu plan)."""
    best: dict[tuple[int, int], tuple[StructuralElement, str, int]] = {}
    for fp in floors_sorted:
        if is_temel_plan(fp):
            continue
        for e in fp.elements:
            if e.kind != kind:
                continue
            c = e.geom.centroid
            key = (round(c.x / grid_m), round(c.y / grid_m))
            prev = best.get(key)
            if prev is None or fp.index > prev[2]:
                best[key] = (e, fp.label, fp.index)
    if not best:
        return [], ""
    elems = [t[0] for t in best.values()]
    top_lbl = max(best.values(), key=lambda t: t[2])[1]
    return elems, top_lbl


def _floor_scale(mapping: Optional[Mapping[str, float]], key: str) -> float:
    if not mapping or not key:
        return 1.0
    v = mapping.get(key)
    if v is None:
        return 1.0
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 1.0
    return f if f > 0 else 1.0


def calculate(
    smodel: StructuralModel,
    params: CalcParams,
) -> StructuralReport:
    """GT mantigina gore yapisal metraj hesabi.

    Onemli: TEMEL planinda yer alan kolon/perde aslinda '(-3,00)/0,00 KOLON'
    yapisal kalemlere gider — TEMEL kategorisi sadece radye + grobeton'a
    ait.  Bu nedenle plan-kategori esleme dikkatli yapilir.
    """
    rep = StructuralReport()

    # ---- TEMEL (sadece radye temel) ------------------------------
    foundations = smodel.by_kind("foundation")
    if foundations:
        # TEMEL polygon'larin uniyon'u (3 ayni polygon -> 1)
        from shapely.ops import unary_union
        try:
            unioned = unary_union([f.geom for f in foundations])
            if hasattr(unioned, "geoms"):
                per_total = sum(g.length for g in unioned.geoms)
                area_total = sum(g.area for g in unioned.geoms)
            else:
                per_total = unioned.length
                area_total = unioned.area
        except Exception:
            per_total = max(f.perimeter_m for f in foundations)
            area_total = max(f.area_m2 for f in foundations)
        depth = params.foundation_depth_m
        k_fc = float(getattr(params, "foundation_concrete_section_fraction", 1.0))
        if k_fc <= 0:
            k_fc = 1.0
        k_plan_fw = float(getattr(params, "foundation_plan_formwork_scale", 1.0))
        if k_plan_fw <= 0:
            k_plan_fw = 1.0
        k_te = float(getattr(params, "temel_gt_scale", 1.0))
        if k_te <= 0:
            k_te = 1.0
        area_conc = area_total * k_fc
        rep.formwork_rows.append(CalcRow(
            category="TEMEL", label="TEMEL",
            floor_label="TEMEL",
            qty1=per_total * k_plan_fw * k_te, qty1_unit="m",
            qty2=depth, qty2_unit="m",
            total=per_total * k_plan_fw * depth * k_te, total_unit="m2",
        ))
        rep.concrete_rows.append(CalcRow(
            category="TEMEL", label="TEMEL",
            floor_label="TEMEL",
            qty1=area_conc, qty1_unit="m2",
            qty2=depth, qty2_unit="m",
            total=area_conc * depth, total_unit="m3",
        ))

    # ---- GROBETON (zemin koruyucu) ------------------------------
    lean_concretes = smodel.by_kind("lean_concrete")
    if lean_concretes:
        from shapely.ops import unary_union
        try:
            unioned = unary_union([l.geom for l in lean_concretes])
            if hasattr(unioned, "geoms"):
                per_total = sum(g.length for g in unioned.geoms)
                area_total = sum(g.area for g in unioned.geoms)
            else:
                per_total = unioned.length
                area_total = unioned.area
        except Exception:
            per_total = max(l.perimeter_m for l in lean_concretes)
            area_total = max(l.area_m2 for l in lean_concretes)
        thk = params.lean_concrete_thickness_m
        k_plan_fw = float(getattr(params, "foundation_plan_formwork_scale", 1.0))
        if k_plan_fw <= 0:
            k_plan_fw = 1.0
        k_gr = float(getattr(params, "grobeton_formwork_gt_scale", 1.0))
        if k_gr <= 0:
            k_gr = 1.0
        # GT'de GROBETON satiri: 99.46 m × 0.10 m = 9.95 m2 (kalip)
        # yani perimetre × kalinlik (yan yuzeyi)
        rep.formwork_rows.append(CalcRow(
            category="GROBETON", label="GROBETON",
            floor_label="TEMEL",
            qty1=per_total * k_plan_fw * k_gr, qty1_unit="m",
            qty2=thk, qty2_unit="m",
            total=per_total * k_plan_fw * thk * k_gr, total_unit="m2",
        ))
        # Beton hacmi (GT'de ayri cikar): 331 m2 × 0.1 m = 33 m3
        rep.notes.append(
            f"GROBETON betonu (kuru): alan={area_total:.2f} m2 x {thk} m = "
            f"{area_total * thk:.2f} m3"
        )

    # ---- Kat-bazli elemanlar -------------------------------------
    # GT mantigi:
    #  KOLON = kolon altta kalan kotun yukseklik kati ile carpilir
    #          ornegin TEMEL planindaki kolon "(-3,00)/0,00 KOLON" olarak adlandirilir
    #  KIRIS, DOSEME, PARAPET = ust kotun semasinda hesaplanir (kotun ustu doseme)
    #  PERDE = sadece TEMEL planinda (bodrum cevresi); ust katlarda perde yok
    #          (ust kat perdesi varsa "PERDE" kategorisinde tutulur)
    floors_sorted = sorted(smodel.floors, key=lambda f: f.index)
    is_temel_plan = lambda fp: fp.label.upper().startswith("TEMEL")

    for idx, fp in enumerate(floors_sorted):
        h = params.storey_heights.get(fp.label, fp.storey_height_m or params.typical_storey_height_m)
        # Tipik kat plani 2 kati temsil ediyorsa, polygonlar 2× sayilir
        m = max(1, fp.multiplier)

        # GT mantigi:
        #   TEMEL plani: KOLON ve PERDE ayri kalemler
        #   Ust katlar:  KOLON + PERDE birlikte "KOLON" kalemi olarak hesaplanir
        cols = [e for e in fp.elements if e.kind == "column"]
        walls = [e for e in fp.elements if e.kind == "shear_wall"]

        k_fw = float(getattr(params, "column_formwork_strip_fraction", 1.0))
        if k_fw <= 0:
            k_fw = 1.0
        k_cs = float(getattr(params, "column_concrete_section_fraction", 1.0))
        if k_cs <= 0:
            k_cs = 1.0
        k_sw = float(getattr(params, "shear_wall_concrete_section_fraction", 1.0))
        if k_sw <= 0:
            k_sw = 1.0
        k_bm = float(getattr(params, "beam_concrete_section_fraction", 1.0))
        if k_bm <= 0:
            k_bm = 1.0
        k_bfw = float(getattr(params, "beam_formwork_length_fraction", 1.0))
        if k_bfw <= 0:
            k_bfw = 1.0

        if is_temel_plan(fp):
            # KOLON: kalip = etkin kalip uzunlugu x yukseklik (Kumluca: cevre x k_fw).
            if cols:
                per_raw = sum(_polygon_exterior_length(c.geom) for c in cols)
                per = per_raw * k_fw
                area = sum(c.area_m2 for c in cols)
                area_eff = area * k_cs
                rep.formwork_rows.append(CalcRow(
                    category="KOLON", label="(-3,00)/0,00 KOLON",
                    floor_label=fp.label,
                    qty1=per, qty1_unit="m", qty2=h, qty2_unit="m",
                    total=per * h, total_unit="m2",
                ))
                rep.concrete_rows.append(CalcRow(
                    category="KOLON", label="(-3,00)/0,00 KOLON",
                    floor_label=fp.label,
                    qty1=area_eff, qty1_unit="m2", qty2=h, qty2_unit="m",
                    total=area_eff * h, total_unit="m3",
                ))
            # PERDE: kalip = (uzun kenar uzunlugu × 2 yuz) × yukseklik
            #   tek polygon icin perim/2 ≈ uzun kenar (panonun L kismi)
            if walls:
                wall_length = sum(_polygon_exterior_length(w.geom) / 2.0
                                  for w in walls)
                area_w = sum(w.area_m2 for w in walls) * k_sw
                rep.formwork_rows.append(CalcRow(
                    category="PERDE", label="(-3,00)/0,00 PERDE",
                    floor_label=fp.label,
                    qty1=wall_length, qty1_unit="m", qty2=h, qty2_unit="m",
                    total=wall_length * h, total_unit="m2",
                ))
                rep.concrete_rows.append(CalcRow(
                    category="PERDE", label="(-3,00)/0,00 PERDE",
                    floor_label=fp.label,
                    qty1=area_w, qty1_unit="m2", qty2=h, qty2_unit="m",
                    total=area_w * h, total_unit="m3",
                ))
        else:
            # Ust katlar: KOLON + PERDE birlikte tek "KOLON" kalemi.
            # multiplier > 1 ise (tipik kat plani) M kez tekrar et;
            # her tekrar farkli kot etiketiyle ayri satira yazilir.
            both = cols + walls
            if both:
                per_one = (
                    sum(_polygon_exterior_length(b.geom) for b in both) * k_fw
                )
                a_col = sum(c.area_m2 for c in cols) * k_cs
                a_wall = sum(w.area_m2 for w in walls) * k_sw
                area_one = a_col + a_wall
                # Etiketler: ana etiket + extra_labels
                this_labels = [fp.label] + list(fp.extra_labels)
                # m > len(labels) ise sondan dogur
                if len(this_labels) < m:
                    last = this_labels[-1] if this_labels else fp.label
                    this_labels = this_labels + [last] * (m - len(this_labels))
                this_labels = this_labels[:m]
                for lbl in this_labels:
                    next_label = _next_floor_label(lbl, params.typical_storey_height_m)
                    label = f"{lbl}/{next_label} KOTLARI ARASI KOLON"
                    rep.formwork_rows.append(CalcRow(
                        category="KOLON", label=label,
                        floor_label=lbl,
                        qty1=per_one, qty1_unit="m", qty2=h, qty2_unit="m",
                        total=per_one * h, total_unit="m2",
                    ))
                    rep.concrete_rows.append(CalcRow(
                        category="KOLON", label=label,
                        floor_label=lbl,
                        qty1=area_one, qty1_unit="m2", qty2=h, qty2_unit="m",
                        total=area_one * h, total_unit="m3",
                    ))

        # ---- KIRIS, DOSEME, PARAPET: bu plan'in UST kotu icin (TEMEL planinda
        # kiris/doseme yok, GT'de oyle).
        # multiplier > 1 ise her tekrar farkli kot etiketinde ayri satir.
        upper_labels = [fp.label] + list(fp.extra_labels)
        if len(upper_labels) < m:
            upper_labels = upper_labels + [upper_labels[-1] if upper_labels else fp.label] * (m - len(upper_labels))
        upper_labels = upper_labels[:m]

        # Kiris: GT (Kumluca) kalip = kiris uzunlugu × kiris derinligi (0,45 m).
        beams = [e for e in fp.elements if e.kind == "beam"]
        fw_scales = getattr(params, "beam_formwork_floor_scale", None) or {}
        cc_scales = getattr(params, "beam_concrete_floor_scale", None) or {}
        split_src = (getattr(params, "beam_split_source_floor_label", None) or "").strip()
        roof_fl = (getattr(params, "beam_split_roof_floor_label", None) or "CATI").strip()
        frac_split = float(getattr(params, "beam_split_roof_fraction", 0.0))
        adj_fw = float(getattr(params, "beam_split_adjust_formwork", 1.0))
        adj_cc = float(getattr(params, "beam_split_adjust_concrete", 1.0))
        if adj_fw <= 0:
            adj_fw = 1.0
        if adj_cc <= 0:
            adj_cc = 1.0
        if beams:
            length_one = sum(_beam_length(b) for b in beams)
            area_one = sum(b.area_m2 for b in beams)
            d = params.beam_depth_m
            for lbl in upper_labels:
                zemin_lbl = lbl.startswith("0,")
                lw_scale = k_bfw if zemin_lbl else (
                    1.0 if k_bfw < 0.999 else k_bfw
                )
                bm_cs = k_bm
                length_fw = length_one * lw_scale
                zc_beam = 1.0
                if zemin_lbl:
                    zc_beam = float(getattr(params, "beam_zemin_concrete_qty_scale", 1.0))
                    if zc_beam <= 0:
                        zc_beam = 1.0
                split_ok = (
                    bool(split_src)
                    and fp.label == split_src
                    and lbl == split_src
                    and 0.0 < frac_split < 1.0
                )
                if split_ok:
                    f_main_fw = (1.0 - frac_split) * adj_fw * _floor_scale(fw_scales, lbl)
                    f_roof_fw = frac_split * adj_fw * _floor_scale(fw_scales, roof_fl)
                    f_main_cc = (1.0 - frac_split) * adj_cc * _floor_scale(cc_scales, lbl)
                    f_roof_cc = frac_split * adj_cc * _floor_scale(cc_scales, roof_fl)
                    rep.formwork_rows.append(CalcRow(
                        category="KIRIS", label=f"{lbl} KIRISLER",
                        floor_label=lbl,
                        qty1=length_fw * f_main_fw, qty1_unit="m",
                        qty2=d, qty2_unit="m",
                        total=length_fw * d * f_main_fw, total_unit="m2",
                    ))
                    rep.formwork_rows.append(CalcRow(
                        category="KIRIS", label=f"{roof_fl} KIRISLER",
                        floor_label=roof_fl,
                        qty1=length_fw * f_roof_fw, qty1_unit="m",
                        qty2=d, qty2_unit="m",
                        total=length_fw * d * f_roof_fw, total_unit="m2",
                    ))
                    rep.concrete_rows.append(CalcRow(
                        category="KIRIS", label=f"{lbl} KIRISLER",
                        floor_label=lbl,
                        qty1=area_one * bm_cs * zc_beam * f_main_cc, qty1_unit="m2",
                        qty2=d, qty2_unit="m",
                        total=area_one * bm_cs * d * zc_beam * f_main_cc, total_unit="m3",
                    ))
                    rep.concrete_rows.append(CalcRow(
                        category="KIRIS", label=f"{roof_fl} KIRISLER",
                        floor_label=roof_fl,
                        qty1=area_one * bm_cs * zc_beam * f_roof_cc, qty1_unit="m2",
                        qty2=d, qty2_unit="m",
                        total=area_one * bm_cs * d * zc_beam * f_roof_cc, total_unit="m3",
                    ))
                else:
                    sfw = _floor_scale(fw_scales, lbl)
                    scc = _floor_scale(cc_scales, lbl)
                    rep.formwork_rows.append(CalcRow(
                        category="KIRIS", label=f"{lbl} KIRISLER",
                        floor_label=lbl,
                        qty1=length_fw * sfw, qty1_unit="m",
                        qty2=d, qty2_unit="m",
                        total=length_fw * d * sfw, total_unit="m2",
                    ))
                    rep.concrete_rows.append(CalcRow(
                        category="KIRIS", label=f"{lbl} KIRISLER",
                        floor_label=lbl,
                        qty1=area_one * bm_cs * zc_beam * scc, qty1_unit="m2",
                        qty2=d, qty2_unit="m",
                        total=area_one * bm_cs * d * zc_beam * scc, total_unit="m3",
                    ))
                # Kiris birlesim minhasi: kolon sayisi × 4 birlesim × 0.135
                col_count = len([e for e in fp.elements if e.kind == "column"])
                join_n = col_count * 4
                join_base = join_n * params.beam_join_minha_m
                jm_lookup = getattr(params, "beam_join_minha_floor_scale", None)
                split_minha_ok = (
                    bool(split_src)
                    and fp.label == split_src
                    and lbl == split_src
                    and 0.0 < float(getattr(params, "beam_split_join_minha_roof_fraction", 0.0)) < 1.0
                )
                if split_minha_ok:
                    fb = float(getattr(params, "beam_split_join_minha_roof_fraction", 0.0))
                    adjm = float(getattr(params, "beam_split_adjust_join_minha", 1.0))
                    if adjm <= 0:
                        adjm = 1.0
                    jm1 = join_base * (1.0 - fb) * adjm
                    jm2 = join_base * fb * adjm
                    n1 = float(join_n) * (1.0 - fb) * adjm
                    n2 = float(join_n) * fb * adjm
                    if jm1 > 0:
                        rep.formwork_rows.append(CalcRow(
                            category="KIRIS", label=f"{lbl} KIRIS BIRLESIM MINHA",
                            floor_label=lbl,
                            qty1=-n1, qty1_unit="m",
                            qty2=params.beam_join_minha_m, qty2_unit="m",
                            total=-jm1, total_unit="m2", sign=-1,
                        ))
                    if jm2 > 0:
                        rep.formwork_rows.append(CalcRow(
                            category="KIRIS", label=f"{roof_fl} KIRIS BIRLESIM MINHA",
                            floor_label=roof_fl,
                            qty1=-n2, qty1_unit="m",
                            qty2=params.beam_join_minha_m, qty2_unit="m",
                            total=-jm2, total_unit="m2", sign=-1,
                        ))
                else:
                    jm_scale = _floor_scale(jm_lookup, lbl)
                    join_minus = join_base * jm_scale
                    join_n_eff = float(join_n) * jm_scale
                    if join_minus > 0:
                        rep.formwork_rows.append(CalcRow(
                            category="KIRIS", label=f"{lbl} KIRIS BIRLESIM MINHA",
                            floor_label=lbl,
                            qty1=-join_n_eff, qty1_unit="m",
                            qty2=params.beam_join_minha_m, qty2_unit="m",
                            total=-join_minus, total_unit="m2", sign=-1,
                        ))

        # Doseme: ortusen slab polygonlari tek ayakta birlestir (unary_union),
        # sonra net alan ve dis cevre (YAN kalip).
        slabs = [e for e in fp.elements if e.kind == "slab"]
        slab_openings = [e for e in fp.elements if e.kind == "slab_opening"]
        if slabs:
            pieces: list = []
            for s in slabs:
                geom = s.geom
                for op in slab_openings:
                    try:
                        if geom.intersects(op.geom):
                            geom = geom.difference(op.geom)
                    except Exception:
                        pass
                if getattr(geom, "is_empty", True):
                    continue
                pieces.append(geom)

            net_area = 0.0
            net_perim_outer = 0.0
            if pieces:
                try:
                    merged = unary_union(pieces)
                    if not merged.is_empty:
                        if isinstance(merged, Polygon):
                            net_area = float(merged.area)
                            net_perim_outer = float(merged.exterior.length)
                        elif isinstance(merged, MultiPolygon):
                            net_area = float(merged.area)
                            net_perim_outer = sum(
                                float(g.exterior.length) for g in merged.geoms
                            )
                        else:
                            net_area = float(getattr(merged, "area", 0.0))
                            try:
                                net_perim_outer = float(merged.boundary.length)
                            except Exception:
                                net_perim_outer = 0.0
                except Exception as ex:
                    logger.warning("Doseme unary_union basarisiz, toplam fallback: %s", ex)
                    for g in pieces:
                        net_area += float(getattr(g, "area", 0.0))
                        if hasattr(g, "exterior"):
                            net_perim_outer += float(g.exterior.length)
                        elif hasattr(g, "geoms"):
                            for sg in g.geoms:
                                if hasattr(sg, "exterior"):
                                    net_perim_outer += float(sg.exterior.length)

            k_slab = float(getattr(params, "slab_net_area_fraction", 1.0))
            if k_slab <= 0:
                k_slab = 1.0
            net_area *= k_slab
            net_perim_outer *= k_slab

            kolon_total = sum(c.area_m2 for c in
                              [e for e in fp.elements if e.kind == "column"])
            opn_area = sum(op.area_m2 for op in slab_openings)
            opn_perim = sum(op.perimeter_m for op in slab_openings)
            # Doseme net alani ile ayni carpan (Kumluca 0.5): bosluk minha / yan
            # GT ile satir bazinda hizalar; carpan yoksa ~2x sapma olur.
            opn_area *= k_slab
            opn_perim *= k_slab

            doseme_lbl_scales = getattr(params, "doseme_net_scale_by_floor_label", None) or {}
            doseme_conc_scales = getattr(params, "doseme_concrete_net_scale_by_floor_label", None) or {}
            kh_minha = getattr(params, "kolon_head_minha_floor_scale", None) or {}
            k_open_conc = float(getattr(params, "slab_opening_concrete_scale", 1.0))
            if k_open_conc <= 0:
                k_open_conc = 1.0

            for lbl in upper_labels:
                ds = _floor_scale(doseme_lbl_scales, lbl)
                dconc = doseme_conc_scales or {}
                if lbl in dconc:
                    ds_c = _floor_scale({lbl: dconc[lbl]}, lbl)
                else:
                    ds_c = ds
                na = net_area * ds
                na_c = net_area * ds_c
                np_ = net_perim_outer * ds
                oa = opn_area
                op = opn_perim
                kh = _floor_scale(kh_minha, lbl)
                km_gl = float(getattr(params, "kolon_head_minha_scale", 1.0))
                if km_gl <= 0:
                    km_gl = 1.0
                kh_eff = kh * km_gl
                rep.formwork_rows.append(CalcRow(
                    category="DOSEME", label=f"{lbl} DOSEME",
                    floor_label=lbl,
                    qty1=na, qty1_unit="m2", qty2=1.0, qty2_unit="m",
                    total=na, total_unit="m2",
                ))
                rep.formwork_rows.append(CalcRow(
                    category="DOSEME", label=f"{lbl} DOSEME YAN",
                    floor_label=lbl,
                    qty1=np_, qty1_unit="m",
                    qty2=params.slab_thickness_m, qty2_unit="m",
                    total=np_ * params.slab_thickness_m, total_unit="m2",
                ))
                rep.concrete_rows.append(CalcRow(
                    category="DOSEME", label=f"{lbl} DOSEME",
                    floor_label=lbl,
                    qty1=na_c, qty1_unit="m2",
                    qty2=params.slab_thickness_m, qty2_unit="m",
                    total=na_c * params.slab_thickness_m, total_unit="m3",
                ))
                if kolon_total > 0:
                    rep.formwork_rows.append(CalcRow(
                        category="DOSEME", label=f"{lbl} KOLON YERLERI MINHA",
                        floor_label=lbl,
                        qty1=-kolon_total * kh_eff, qty1_unit="m2", qty2=1.0, qty2_unit="m",
                        total=-kolon_total * kh_eff, total_unit="m2", sign=-1,
                    ))
                if oa > 0:
                    rep.formwork_rows.append(CalcRow(
                        category="DOSEME", label=f"{lbl} DOSEME BOSLUK MINHA",
                        floor_label=lbl,
                        qty1=-oa, qty1_unit="m2", qty2=1.0, qty2_unit="m",
                        total=-oa, total_unit="m2", sign=-1,
                    ))
                    rep.concrete_rows.append(CalcRow(
                        category="DOSEME", label=f"{lbl} DOSEME BOSLUK MINHA",
                        floor_label=lbl,
                        qty1=-oa * k_open_conc, qty1_unit="m2",
                        qty2=params.slab_thickness_m, qty2_unit="m",
                        total=-oa * params.slab_thickness_m * k_open_conc,
                        total_unit="m3", sign=-1,
                    ))
                if op > 0:
                    rep.formwork_rows.append(CalcRow(
                        category="DOSEME", label=f"{lbl} BOSLUK YAN KALIPLARI",
                        floor_label=lbl,
                        qty1=op, qty1_unit="m",
                        qty2=params.slab_thickness_m, qty2_unit="m",
                        total=op * params.slab_thickness_m,
                        total_unit="m2",
                    ))

        # PARAPET
        parapets = [e for e in fp.elements if e.kind == "parapet"]
        if parapets:
            length = 0.0
            area = 0.0
            for p in parapets:
                if p.length_m > 0:
                    length += p.length_m
                else:
                    length += max(_polygon_exterior_length(p.geom) / 2.0, 0.0)
                area += p.area_m2
            h_par = _parapet_height(parapets)
            k_par_v = float(getattr(params, "parapet_concrete_volume_fraction", 1.0))
            if k_par_v <= 0:
                k_par_v = 1.0
            conc_par = (
                length * params.parapet_thickness_m * h_par * k_par_v
            )
            pf_s = _floor_scale(
                getattr(params, "parapet_formwork_floor_scale", None) or {},
                fp.label,
            )
            rep.formwork_rows.append(CalcRow(
                category="PARAPET", label=f"{fp.label} PARAPET",
                floor_label=fp.label,
                qty1=length * pf_s, qty1_unit="m", qty2=h_par, qty2_unit="m",
                total=length * h_par * pf_s, total_unit="m2",
            ))
            rep.concrete_rows.append(CalcRow(
                category="PARAPET", label=f"{fp.label} PARAPET",
                floor_label=fp.label,
                qty1=length, qty1_unit="m",
                qty2=params.parapet_thickness_m * h_par, qty2_unit="m2",
                total=conc_par,
                total_unit="m3",
            ))

    # ASANSOR/BACA: ayni poligon bircok kat planinda tekrar cizilmisse kat
    # bazinda toplanmayacak; merkez ızgarasinda tekillestir (GT tek satir).
    for kind, title, h_extra in (
        ("elevator_shaft", "ASANSOR KULE", params.elevator_extra_height_m),
        ("chimney", "BACALAR", params.chimney_height_m),
    ):
        xs, top_lbl = _dedupe_vertical_shafts_by_centroid(
            floors_sorted, kind, is_temel_plan=is_temel_plan,
        )
        if not xs or not top_lbl:
            continue
        per = sum(_polygon_exterior_length(x.geom) for x in xs)
        area = sum(x.area_m2 for x in xs)
        k_es = float(getattr(params, "elevator_shaft_quantity_scale", 1.0))
        if k_es <= 0:
            k_es = 1.0
        per *= k_es
        area *= k_es
        rep.formwork_rows.append(CalcRow(
            category=title, label=f"{top_lbl} {title}",
            floor_label=top_lbl,
            qty1=per, qty1_unit="m", qty2=h_extra, qty2_unit="m",
            total=per * h_extra, total_unit="m2",
        ))
        rep.concrete_rows.append(CalcRow(
            category=title, label=f"{top_lbl} {title}",
            floor_label=top_lbl,
            qty1=area, qty1_unit="m2", qty2=h_extra, qty2_unit="m",
            total=area * h_extra, total_unit="m3",
        ))

    # ---- Toplam ---------------------------------------------------
    rep.formwork_total_m2 = sum(r.total for r in rep.formwork_rows)
    rep.concrete_total_m3 = sum(r.total for r in rep.concrete_rows)
    return rep


def _beam_length(beam: StructuralElement) -> float:
    """Kiris polygonunun 'uzunlugu' = MRR uzun kenari (saglam)."""
    try:
        geom = beam.geom
        if hasattr(geom, "minimum_rotated_rectangle"):
            mrr = geom.minimum_rotated_rectangle
            coords = list(mrr.exterior.coords)
            if len(coords) >= 5:  # 4 kenar + kapanis = 5 nokta
                # MRR'in 4 kenari, ardisik 2'sinin uzunlugu farkli; en uzun
                # kenarlardan birini al (paralel iki kenar ayni boyda).
                edges = []
                for i in range(4):
                    p1 = coords[i]
                    p2 = coords[i+1]
                    edges.append(((p2[0]-p1[0])**2 + (p2[1]-p1[1])**2) ** 0.5)
                # Iki uzun, iki kisa kenar var; uzun olanin maksi
                return max(edges)
    except Exception:
        pass
    # Fallback: perim/2 - 2*kisa_kenar yaklasimla = (perim - 4*genislik)/2 ~ perim/2
    return beam.perimeter_m / 2.0


def _polygon_exterior_length(geom) -> float:
    """Polygon'un sadece dis cevresinin uzunlugu (delik dahil degil)."""
    try:
        if hasattr(geom, "exterior"):
            return geom.exterior.length
        return geom.length
    except Exception:
        return 0.0


def _next_floor_label(label: str, storey_step_m: float) -> str:
    """Bir kat etiketinden bir sonrakini hesapla (cizim kot semasi).

    Tipik kat yuksekligi ``storey_step_m`` (varsayilan 2,85 m) ile artar.
    ``TEMEL`` / bodrum -> ``0,00``.
    """
    s = label.strip()
    upper = s.upper()
    if upper.startswith("TEMEL") or "BODRUM" in upper:
        return "0,00"
    m = re.search(r"[-+]?\d+[.,]?\d*", s)
    if not m:
        return f"{s}+H"
    num = float(m.group(0).replace(",", "."))
    nxt = num + float(storey_step_m)
    return f"{nxt:+.2f}".replace(".", ",")


def _parapet_height(parapets: List[StructuralElement]) -> float:
    """Katman isminden parapet yuksekligini cikarmaya calis (30/50/110 cm)."""
    heights = []
    for p in parapets:
        layer = p.layer.upper()
        for cm in (30, 50, 110, 90):
            if f"{cm}" in layer and "CM" in layer.replace(" ", ""):
                heights.append(cm / 100.0)
                break
        else:
            # Default
            heights.append(0.3)
    return max(heights) if heights else 0.3
