"""DXF'ten yapisal elemanlari (kolon, perde, kiris, doseme...) cikarir.

Strateji:
1. Yapisal autodetect ile her katmanin ElementKind'ini bul.
2. O katmanlardaki kapali polylineleri (Polygon) ve hatch boundary'leri
   eleman listesine cevir.
3. Geometrik kalite kontrolu: cok kucuk (toleranslar altinda) veya
   gecersiz polygonlari at; ayni geometriyi temsil eden duplikatlari
   birlestir.
4. Acik polylineler (parapet uzunlugu) icin LineString olarak ekle.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional, Sequence, Set, Tuple

from shapely.geometry import LineString, Polygon
from shapely.ops import unary_union

from ..cad_io.dxf_reader import RawCadModel
from .elements import ElementKind, StructuralElement
from .layer_detection import StructuralLayerReport, detect_structural_layers

logger = logging.getLogger(__name__)


def _safe_polygon(points: Sequence[Tuple[float, float]]) -> Optional[Polygon]:
    if len(points) < 3:
        return None
    try:
        p = Polygon(points)
        if not p.is_valid:
            p = p.buffer(0)
        if p.is_empty:
            return None
        if p.area < 1e-6:
            return None
        return p
    except Exception:
        return None


# Tek-primary kindler: ayni kind'a birden cok katman duserse cogu
# zaman duplicate.  PARAPET/MERDIVEN gibi kategoriler ise farkli
# alt-tipler icerir (30CM PARAPET, 90CM PARAPET, vs.) o yuzden
# multi-layer kabul.
_SINGLE_PRIMARY_KINDS = {
    "column", "shear_wall", "beam", "slab", "slab_opening",
    "foundation", "lean_concrete", "elevator_shaft",
}


def _select_primary_layers_per_kind(
    layer_report: StructuralLayerReport,
    model: RawCadModel,
    min_share: float = 0.50,
) -> Dict[str, List[str]]:
    """Her kind icin tutulacak katman listesini sec.

    Tek-primary kind'larda (KOLON, PERDE, KIRIS, ...): en cok polygon'lu
    katman primary; diger katmanlar primary'in `min_share`'inin altinda
    ise duplicate kabul edilir ve atilir.

    Multi-primary kind'larda (PARAPET, MERDIVEN, ...): tum katmanlar
    kabul edilir.
    """
    primary: Dict[str, List[str]] = {}
    for kind, layers in layer_report.kind_to_layers.items():
        if not layers:
            continue
        if kind not in _SINGLE_PRIMARY_KINDS:
            primary[kind] = list(layers)
            continue
        counts: List[Tuple[str, int]] = []
        for layer in layers:
            n = sum(1 for p in model.polylines if p.layer == layer and p.closed)
            counts.append((layer, n))
        counts.sort(key=lambda x: -x[1])
        if not counts:
            primary[kind] = []
            continue
        top_n = counts[0][1]
        kept = [counts[0][0]]
        dropped = []
        for layer, n in counts[1:]:
            if top_n > 0 and n / top_n >= min_share:
                kept.append(layer)
            else:
                dropped.append((layer, n))
        primary[kind] = kept
        if dropped:
            logger.info(
                "Primary '%s' = %r (%d polygon); ikincil duplicate katmanlar atildi: %s",
                kind, kept, top_n, dropped,
            )
    return primary


def extract_structural_elements(
    model: RawCadModel,
    layer_report: Optional[StructuralLayerReport] = None,
    min_polygon_area_m2: float = 0.005,
    layer_always_keep: Optional[Set[str]] = None,
    *,
    include_standalone_lines: bool = False,
) -> Tuple[List[StructuralElement], StructuralLayerReport]:
    """Modeldeki tum yapisal elemanlari cikar.

    Eger `layer_report` None ise otomatik tespit calistirilir.

    Ayni kind'a birden fazla katman atandiginda, sadece "primary"
    olanin polygonlarini kabul ederiz; ikincil katmanlar genelde cift
    cizim icerir.

    `layer_always_keep`: YAML/UI ile manuel eklenen katmanlar; primary
    seciminde dusmese bile cikarimda tutulur.
    """
    if layer_report is None:
        from ..cad_io.dxf_reader import inventory_layers
        inv = inventory_layers(model)
        layer_report = detect_structural_layers(model.layers, layer_inventory=inv)

    primary_per_kind = _select_primary_layers_per_kind(layer_report, model)
    keep = layer_always_keep or set()
    if keep:
        for kind, layers in layer_report.kind_to_layers.items():
            for lay in layers:
                if lay in keep:
                    plist = primary_per_kind.setdefault(kind, [])
                    if lay not in plist:
                        plist.append(lay)

    elements: List[StructuralElement] = []

    # Kapali polyline'lardan
    for poly in model.polylines:
        kind = layer_report.layer_to_kind.get(poly.layer)
        if not kind:
            continue
        # Primary kontrol: sadece primary katman(lar)dan kabul et
        primary_list = primary_per_kind.get(kind, [])
        if primary_list and poly.layer not in primary_list:
            continue
        if poly.closed and len(poly.points) >= 3:
            shp = _safe_polygon(poly.points)
            if shp is None or shp.area < min_polygon_area_m2:
                continue
            elements.append(StructuralElement.from_polygon(
                kind=kind, layer=poly.layer, polygon=shp,
            ))
        else:
            # Acik polyline: parapet uzunlugu, kiris hattı, vs.
            try:
                ls = LineString(poly.points)
                if ls.length < 0.05:
                    continue
                elements.append(StructuralElement(
                    kind=kind,
                    layer=poly.layer,
                    geom=ls,
                    area_m2=0.0,
                    perimeter_m=0.0,
                    length_m=ls.length,
                ))
            except Exception:
                continue

    # Hatch boundary'lerinden
    for hatch in model.hatches:
        kind = layer_report.layer_to_kind.get(hatch.layer)
        if not kind:
            continue
        shp = _safe_polygon(hatch.boundary)
        if shp is None or shp.area < min_polygon_area_m2:
            continue
        elements.append(StructuralElement.from_polygon(
            kind=kind, layer=hatch.layer, polygon=shp,
        ))

    # Faz 3: standalone LINE entity'leri (DXF "LINE", polyline degil) — bazi
    # firmalar kirisi tek bir LINE olarak ciziyor. Opsiyonel; default kapali
    # cunku KOLON/PERDE katmaninda da yardimci LINE'lar olabilir, yanlis
    # eleman uretebilir.
    if include_standalone_lines:
        line_kinds_allowed = {"beam"}  # sadece kiris adayi katmanlardan
        for ln in model.lines:
            kind = layer_report.layer_to_kind.get(ln.layer)
            if kind not in line_kinds_allowed:
                continue
            primary_list = primary_per_kind.get(kind, [])
            if primary_list and ln.layer not in primary_list:
                continue
            try:
                ls = LineString([ln.start, ln.end])
                if ls.length < 0.5:  # cok kisa cizgi kiris degildir (detay)
                    continue
                elements.append(StructuralElement(
                    kind=kind, layer=ln.layer, geom=ls,
                    area_m2=0.0, perimeter_m=0.0, length_m=ls.length,
                ))
            except Exception:
                continue

    # Bilgilendirme
    counts: Dict[str, int] = {}
    for el in elements:
        counts[el.kind] = counts.get(el.kind, 0) + 1
    logger.info("Yapisal extractor: %d eleman cikarildi (%s)",
                len(elements),
                ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    return elements, layer_report


def deduplicate(
    elements: Sequence[StructuralElement],
    iou_threshold: float = 0.7,
    centroid_tol_m: float = 0.30,
    area_tol_pct: float = 0.20,
) -> List[StructuralElement]:
    """Ayni geometriyi temsil eden elemanlari birlestirir.

    Yapisal cizimlerde ayni kolon/perde polygon'u birden cok defa cizilir
    (TEMEL plani + zemin kat plani + 3D detay).  Bu fonksiyon onlari
    teke indirir.

    Strateji (her kind icin ayri):
    1) Centroid `centroid_tol_m` icinde VE alan farki yuzde
       `area_tol_pct`'dan az ise duplicate (hizli, hassas).
    2) IoU >= `iou_threshold` ise duplicate (yedek, polygonlar tam ust uste).
    """
    out: List[StructuralElement] = []
    by_kind: Dict[str, List[StructuralElement]] = {}
    for el in elements:
        by_kind.setdefault(el.kind, []).append(el)
    for kind, lst in by_kind.items():
        kept_data: List[Tuple[StructuralElement, Tuple[float, float], float]] = []
        for el in lst:
            try:
                c = el.geom.centroid
                cxy = (c.x, c.y)
                area = el.area_m2 if el.area_m2 > 0 else getattr(el.geom, "area", 0.0)
            except Exception:
                cxy = (0.0, 0.0)
                area = 0.0
            duplicate = False
            for prev_el, prev_xy, prev_area in kept_data:
                # 1) Centroid + alan
                dx = cxy[0] - prev_xy[0]
                dy = cxy[1] - prev_xy[1]
                dist = (dx * dx + dy * dy) ** 0.5
                if dist < centroid_tol_m and prev_area > 0:
                    rel = abs(area - prev_area) / prev_area
                    if rel <= area_tol_pct:
                        duplicate = True
                        break
                # 2) IoU (sadece centroidler 1 m icindeyse hesapla, performans)
                if dist < 1.0:
                    try:
                        inter = el.geom.intersection(prev_el.geom).area
                        if inter > 0:
                            uni = el.geom.union(prev_el.geom).area
                            if uni > 0 and inter / uni >= iou_threshold:
                                duplicate = True
                                break
                    except Exception:
                        pass
            if not duplicate:
                out.append(el)
                kept_data.append((el, cxy, area))
    logger.info("Deduplicate: %d -> %d (kind bazli)", len(elements), len(out))
    return out


def containment_dedupe(
    elements: Sequence[StructuralElement],
) -> List[StructuralElement]:
    """Ic ice cizilmis polygonlari teke indirger.

    Bazi DWG'lerde bir kolon hem dis kontur hem ic tarama-sinir polygon'u
    olarak iki kez cizilir.  Eger A polygonun centroid'i B polygon'un
    ICINDE ve A < B ise, A duplicate kabul edilir ve atilir.

    Yalnizca ayni kind icinde yapilir.
    """
    by_kind: Dict[str, List[StructuralElement]] = {}
    for el in elements:
        by_kind.setdefault(el.kind, []).append(el)

    out: List[StructuralElement] = []
    for kind, lst in by_kind.items():
        # Buyukten kucuge sirala (buyukler tutulur, icindeki kucukler atilir)
        sorted_lst = sorted(lst, key=lambda x: -x.area_m2)
        kept = []
        for el in sorted_lst:
            try:
                cx, cy = el.geom.centroid.x, el.geom.centroid.y
            except Exception:
                kept.append(el)
                continue
            inside_someone = False
            for other in kept:
                try:
                    if (other.area_m2 > el.area_m2 * 1.05 and
                        other.geom.contains(el.geom.centroid)):
                        # Ek kontrol: el alan'i other'in %50'sinden buyuk olamaz
                        # (cunku ic tarama dis konturun kucuk parcasi olmali)
                        if el.area_m2 / max(other.area_m2, 0.001) <= 0.95:
                            inside_someone = True
                            break
                except Exception:
                    continue
            if not inside_someone:
                kept.append(el)
        out.extend(kept)
    logger.info("Containment dedupe: %d -> %d", len(elements), len(out))
    return out


def hash_dedupe_by_geometry(
    elements: Sequence[StructuralElement],
    centroid_round_m: float = 0.20,
    area_round_pct: float = 0.05,
) -> List[StructuralElement]:
    """Tam ayni geometride iki kez cizilen polygonlari hash bazli atar.

    Centroid (round) + alan (round) hash'i ayni olanlari teke indirger.
    Cok hizli, agresif.  Kullanim: deduplicate cagri oncesi hizli cikis.
    """
    seen: Dict[Tuple[str, int, int, int], StructuralElement] = {}
    for el in elements:
        try:
            c = el.geom.centroid
            cx = round(c.x / centroid_round_m) * centroid_round_m
            cy = round(c.y / centroid_round_m) * centroid_round_m
            a = el.area_m2 if el.area_m2 > 0 else getattr(el.geom, "area", 0.0)
            # Alan icin %5'lik bucket
            a_bucket = round(a / max(a * area_round_pct, 0.01))
        except Exception:
            cx, cy, a_bucket = 0, 0, 0
        key = (el.kind, int(cx * 100), int(cy * 100), int(a_bucket))
        if key not in seen:
            seen[key] = el
    out = list(seen.values())
    logger.info("Hash dedupe: %d -> %d (centroid+area hash)",
                len(elements), len(out))
    return out


def filter_by_plan(
    elements: Sequence[StructuralElement],
    plan_kinds_allowed: Optional[Dict[str, set]] = None,
) -> List[StructuralElement]:
    """Plan-baglami filtresi: TEMEL planinda kiris/doseme/perde olmamasi
    gerekirse cikar, vs.

    `plan_kinds_allowed`: {'TEMEL': {'foundation', 'lean_concrete',
    'column', 'shear_wall'}, ...} — eger eleman bu kume disindaysa atilir.
    """
    if plan_kinds_allowed is None:
        return list(elements)
    out = []
    for el in elements:
        floor = (el.floor_label or "").upper()
        allowed = None
        for fname, kinds in plan_kinds_allowed.items():
            if fname.upper() == floor:
                allowed = kinds
                break
        if allowed is None or el.kind in allowed:
            out.append(el)
    return out


def collapse_overlapping(
    elements: Sequence[StructuralElement],
    overlap_iou: float = 0.5,
) -> List[StructuralElement]:
    """Cok ortusen ayni-kind polygonlari birlestirir (union).

    Foundation gibi parcali cizilmis temelleri tek elemana indirger.
    Iki polygon IoU >= overlap_iou ise unioned.
    """
    out: List[StructuralElement] = []
    by_kind: Dict[str, List[StructuralElement]] = {}
    for el in elements:
        by_kind.setdefault(el.kind, []).append(el)
    for kind, lst in by_kind.items():
        merged: List[StructuralElement] = []
        used = [False] * len(lst)
        for i, a in enumerate(lst):
            if used[i]:
                continue
            geom_a = a.geom
            for j in range(i + 1, len(lst)):
                if used[j]:
                    continue
                b = lst[j]
                try:
                    if not geom_a.intersects(b.geom):
                        continue
                    inter = geom_a.intersection(b.geom).area
                    union = geom_a.union(b.geom).area
                    if union > 0 and inter / union >= overlap_iou:
                        geom_a = geom_a.union(b.geom)
                        used[j] = True
                except Exception:
                    continue
            try:
                from shapely.geometry import MultiPolygon, Polygon
                if isinstance(geom_a, (Polygon, MultiPolygon)):
                    merged.append(StructuralElement(
                        kind=kind, layer=a.layer, geom=geom_a,
                        area_m2=geom_a.area, perimeter_m=geom_a.length,
                        length_m=0.0,
                        floor_label=a.floor_label, floor_index=a.floor_index,
                        plan_index=a.plan_index, properties=dict(a.properties),
                    ))
                else:
                    merged.append(a)
            except Exception:
                merged.append(a)
            used[i] = True
        out.extend(merged)
    return out
