"""DWG'deki yan yana cizilmis kat planlarini otomatik tespit.

Yapisal cizimlerde her kat genelde ayni dosyada yan yana plan bloklari
olarak cizilir (TEMEL, 0,00 KAT PLANI, 3,00 KAT PLANI, ...).  Bizim
yapisal extractor'imizin polygonlari dogru kata atamasi icin bu plan
kumelerini bbox tabanli kumelemeyle bulmamiz lazim.

Strateji:
1. Tum yapisal kapali polygonlarin centroid'lerini topla.
2. Centroid'leri x ekseninde ardisik kumelere ayir (genis bos seritleri
   delimiter olarak kullanir).  Her kume = bir plan.
3. Kume sayisi konfigte beklenen kat sayisina yakinsa (ve yetmezse gap
   threshold'u dinamik dustur), plan-kat eslemesini sirayla yap.
4. Plan etiket metinlerinden "0,00", "3,00" gibi kot bilgisi cikarmaya
   calis (TEXT/MTEXT entity'lerini centroid'in icinde olanla esle).
5. Kalan elemanlar `unassigned` olarak rapor edilir.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from shapely.geometry import Point

from ..cad_io.dxf_reader import CadText, RawCadModel
from .elements import FloorPlan, StructuralElement

logger = logging.getLogger(__name__)


# Tipik kat etiketi: "+0.00", "0,00", "3,00 KAT PLANI", "TEMEL PLANI", "-3.00"
_FLOOR_LABEL_RE = re.compile(
    r"(?P<full>"
    r"(?P<sign>[+\-])?\s*(?P<num>\d{1,2}[.,]\d{1,2})\s*(?:M)?"
    r"|TEMEL"
    r"|GRO[\s_-]?BETON"
    r"|CATI|ÇATI"
    r"|ASANSOR\s*KULE|ASANSÖR\s*KULE"
    r")",
    re.IGNORECASE,
)


@dataclass
class FloorAssignment:
    """Bir plan kumesinin geometrik sınırı + (varsa) etiketi."""

    bbox: Tuple[float, float, float, float]
    label: Optional[str] = None
    elevation_m: Optional[float] = None


def _cluster_axis(values: Sequence[float], gap_factor: float = 1.2) -> List[Tuple[float, float]]:
    """1B kumeleme: tek bir eksende deger kumeleri bulur.

    ``gap_factor``: bir bosluk medyan_aralik * gap_factor'tan buyukse kume
    siniri olarak kabul edilir. ``Faz 2``: eksen-bagimsiz, hem x hem y icin
    kullanilir.
    """
    if not values:
        return []
    sorted_v = sorted(values)
    if len(sorted_v) == 1:
        return [(sorted_v[0], sorted_v[0])]
    diffs = [b - a for a, b in zip(sorted_v, sorted_v[1:])]
    diffs_pos = [d for d in diffs if d > 1e-9]
    if not diffs_pos:
        return [(sorted_v[0], sorted_v[-1])]
    diffs_pos_sorted = sorted(diffs_pos)
    median = diffs_pos_sorted[len(diffs_pos_sorted) // 2]
    threshold = max(median * gap_factor, 1.5)  # en az 1.5 metre

    clusters: List[List[float]] = [[sorted_v[0]]]
    for prev, curr in zip(sorted_v, sorted_v[1:]):
        if curr - prev > threshold:
            clusters.append([curr])
        else:
            clusters[-1].append(curr)
    return [(c[0], c[-1]) for c in clusters]


# Geri uyum icin eski ad da kullanilabilir; iceride ayni fonksiyondur.
_cluster_x = _cluster_axis


def _bbox_of_polygons(polys) -> Tuple[float, float, float, float]:
    bounds = [p.bounds for p in polys if p is not None]
    if not bounds:
        return (0, 0, 0, 0)
    return (
        min(b[0] for b in bounds),
        min(b[1] for b in bounds),
        max(b[2] for b in bounds),
        max(b[3] for b in bounds),
    )


def _select_axis_auto(
    centroids: List[Tuple[float, float, "StructuralElement"]],
    expected_floor_count: Optional[int],
) -> str:
    """``axis='auto'`` icin x ve y eksenlerini deneyip ``expected_floor_count``'a
    yakin olan ekseni doner. Beklenti yoksa kume sayisi cok olan eksen secilir.
    """
    xs = [c[0] for c in centroids]
    ys = [c[1] for c in centroids]
    n_x = len(_cluster_axis(xs))
    n_y = len(_cluster_axis(ys))
    if expected_floor_count:
        if abs(n_x - expected_floor_count) <= abs(n_y - expected_floor_count):
            return "x"
        return "y"
    return "x" if n_x >= n_y else "y"


def detect_plan_groups(
    elements: Sequence[StructuralElement],
    expected_floor_count: Optional[int] = None,
    min_elements_per_group: int = 3,
    *,
    axis: str = "x",
) -> List[FloorAssignment]:
    """Tum yapisal elemanlardan kat plan kumelerini cikarir.

    Plan kumeleri ``axis`` ekseninde ardisik gruplara ayrilir; her grup bir
    kat plani olarak yorumlanir. Sonuc bir bbox listesidir; etiket sonra
    text-overlay aramasi ile eklenir.

    Faz 2: ``axis``: ``"x"`` (yatay layout, Kumluca default), ``"y"`` (dusey
    layout), ya da ``"auto"`` (her iki yon denenir, ``expected_floor_count``'a
    yakin olan secilir).
    """
    centroids = []
    for el in elements:
        try:
            c = el.geom.centroid
            centroids.append((c.x, c.y, el))
        except Exception:
            continue
    if not centroids:
        return []

    if axis not in {"x", "y", "auto"}:
        logger.warning("detect_plan_groups: bilinmeyen axis=%r, 'x' kullaniliyor", axis)
        axis = "x"
    if axis == "auto":
        axis = _select_axis_auto(centroids, expected_floor_count)
        logger.info("detect_plan_groups: axis='auto' -> '%s' secildi", axis)

    coord_index = 0 if axis == "x" else 1
    coords = [c[coord_index] for c in centroids]
    axis_clusters = _cluster_axis(coords)

    # Eger expected'a yakin degilse, gap_factor'u arttirip yeniden dene
    if expected_floor_count and abs(len(axis_clusters) - expected_floor_count) > 0:
        candidates = []
        for f in [round(0.5 + i * 0.1, 2) for i in range(50)]:  # 0.5..5.4
            try_clusters = _cluster_axis(coords, gap_factor=f)
            candidates.append((abs(len(try_clusters) - expected_floor_count), f, try_clusters))
            if len(try_clusters) == expected_floor_count:
                axis_clusters = try_clusters
                logger.info("Plan kumesi gap_factor=%s ile %d kume bulundu (axis=%s)",
                            f, len(try_clusters), axis)
                break
        else:
            # Tam eslesme yok; en yakin
            candidates.sort()
            _, best_f, best_cl = candidates[0]
            axis_clusters = best_cl
            logger.info("Plan kumesi gap_factor=%s ile %d kume (beklenen=%d, axis=%s)",
                        best_f, len(best_cl), expected_floor_count, axis)

    # Her kume icin bbox + eleman sayisi cikar
    raw_assignments: List[Tuple[FloorAssignment, int]] = []
    for lo, hi in axis_clusters:
        polys_in = [
            el.geom for x, y, el in centroids
            if lo - 0.001 <= (x if axis == "x" else y) <= hi + 0.001
        ]
        if len(polys_in) < min_elements_per_group:
            continue
        bbox = _bbox_of_polygons(polys_in)
        raw_assignments.append((FloorAssignment(bbox=bbox), len(polys_in)))

    # Eger hala fazla kume varsa, en kucuk eleman sayili olanlari at
    # (gercek planlar yapisal eleman sayisi acisindan birbirine yakin
    # olmaya egilimlidir; kucuk kumeler genelde detay/gorunus parcalari)
    bbox_axis_idx = 0 if axis == "x" else 1  # bbox tuple icinde minx=0, miny=1
    if expected_floor_count and len(raw_assignments) > expected_floor_count:
        # Eleman sayisina gore azalan sirala, ilk N'i tut, sonra eksen sirasiyla sirala
        raw_assignments.sort(key=lambda x: x[1], reverse=True)
        kept = raw_assignments[:expected_floor_count]
        kept.sort(key=lambda x: x[0].bbox[bbox_axis_idx])
        assignments = [a for a, _ in kept]
        dropped = raw_assignments[expected_floor_count:]
        logger.info("Plan kume budamasi: %d kume tutuldu, %d kume atildi (kucuk).",
                    len(assignments), len(dropped))
    else:
        assignments = [a for a, _ in raw_assignments]
        # Eksen sirasiyla sirala (yatay -> sol-sag, dusey -> alt-ust)
        assignments.sort(key=lambda a: a.bbox[bbox_axis_idx])

    logger.info("Tespit edilen plan kumesi sayisi: %d (beklenen=%s)",
                len(assignments), expected_floor_count)
    return assignments


def parse_floor_label(text: str) -> Tuple[Optional[str], Optional[float]]:
    """Bir metinden kat etiketi ve kot degerini cikarir."""
    if not text:
        return None, None
    s = text.strip()
    upper = s.upper()
    if "TEMEL" in upper:
        return "TEMEL", None
    if "GROBETON" in upper or "GRO BETON" in upper:
        return "GROBETON", None
    if "ASANSÖR KULE" in upper or "ASANSOR KULE" in upper:
        return "ASANSOR KULE", None
    if "CATI" in upper or "ÇATI" in upper:
        return "CATI", None
    m = _FLOOR_LABEL_RE.search(s)
    if not m:
        return None, None
    num = m.group("num")
    if not num:
        return None, None
    elev = float(num.replace(",", "."))
    if m.group("sign") == "-":
        elev = -elev
    return f"{elev:+.2f}", elev


def attach_floor_labels(
    plans: List[FloorAssignment],
    texts: Sequence[CadText],
    floor_label_layers: Optional[Sequence[str]] = None,
) -> List[FloorAssignment]:
    """Her plan kumesi icin icindeki metinleri tarayip etiket ve kot atar.

    Yalniz `floor_label_layers` ya da heuristic olarak buyuk yazi
    boyutu olan TEXT'lere bakar (kat baslıklari genelde buyuktur).
    """
    label_layers = {l.upper() for l in (floor_label_layers or [])}

    # Plan kumelerini sol-saga sirala
    plans_sorted = sorted(plans, key=lambda p: p.bbox[0])
    for plan in plans_sorted:
        xmin, ymin, xmax, ymax = plan.bbox
        # plan icindeki metinleri topla
        candidates: List[Tuple[float, str, float]] = []  # (height, text, y)
        for t in texts:
            x, y = t.insert
            if not (xmin - 1.0 <= x <= xmax + 1.0):
                continue
            # plan disinda buyuk basliklar olabilir; y'yi de daralt
            if not (ymin - 5.0 <= y <= ymax + 10.0):
                continue
            txt_label, elev = parse_floor_label(t.text)
            if not txt_label:
                continue
            if label_layers and t.layer.upper() not in label_layers:
                # tercih ediyoruz ama kati zorunlu degil
                pass
            candidates.append((t.height or 0.0, txt_label, elev or 0.0))
        if not candidates:
            continue
        # En cok tekrar eden ya da en buyuk yaziyi sec
        candidates.sort(key=lambda c: c[0], reverse=True)
        plan.label = candidates[0][1]
        plan.elevation_m = candidates[0][2] if candidates[0][2] != 0 else None
    return plans_sorted


def assign_elements_to_plans(
    elements: Sequence[StructuralElement],
    plans: List[FloorAssignment],
    config_floors: Optional[List[Dict[str, float]]] = None,
    typical_storey_height_m: float = 2.85,
    *,
    axis: str = "x",
) -> Tuple[List[FloorPlan], List[StructuralElement]]:
    """Her elemani ``axis`` ekseninde en uygun plan kumesine yerlestirir.

    ``axis``: ``"x"`` (yatay layout) veya ``"y"`` (dusey layout). Plan'lar
    eksen sirasiyla siralanir (sol-sag veya alt-ust).

    ``config_floors``: Eger kullanici elle "TEMEL,0.00,3.00,..." vermisse,
    plan sayisi ile eslesirse o etiketler kullanilir; eslesmezse otomatik.
    """
    if not plans:
        return [], list(elements)

    if axis not in {"x", "y"}:
        axis = "x"
    bbox_axis_idx = 0 if axis == "x" else 1
    # Plan kumelerini eksen sirasiyla sirala (x:sol-sag / y:alt-ust)
    sorted_plans = sorted(plans, key=lambda p: p.bbox[bbox_axis_idx])

    # Config etiketleri varsa, sayilari esitse uygula
    if config_floors and len(config_floors) == len(sorted_plans):
        for idx, (plan, cfg) in enumerate(zip(sorted_plans, config_floors)):
            plan.label = cfg.get("label", plan.label or f"KAT-{idx}")
            plan.elevation_m = cfg.get("elevation_m", plan.elevation_m)

    # FloorPlan nesneleri kur
    floor_plans: List[FloorPlan] = []
    for idx, p in enumerate(sorted_plans):
        elev = p.elevation_m if p.elevation_m is not None else float(idx) * typical_storey_height_m
        h_storey = typical_storey_height_m
        if config_floors and idx < len(config_floors):
            h_storey = config_floors[idx].get("storey_height_m", typical_storey_height_m)
        floor_plans.append(FloorPlan(
            label=p.label or f"KAT-{idx}",
            index=idx,
            elevation_m=elev,
            storey_height_m=h_storey,
            bbox=p.bbox,
        ))

    unassigned: List[StructuralElement] = []
    for el in elements:
        try:
            c = el.geom.centroid
            cx, cy = c.x, c.y
        except Exception:
            unassigned.append(el)
            continue
        c_axis = cx if axis == "x" else cy
        # Hangi planin eksen araliginda?
        chosen: Optional[FloorPlan] = None
        for fp in floor_plans:
            lo = fp.bbox[bbox_axis_idx]
            hi = fp.bbox[bbox_axis_idx + 2]
            if lo - 0.001 <= c_axis <= hi + 0.001:
                chosen = fp
                break
        if chosen is None:
            # En yakin plan
            best = None
            best_dist = float("inf")
            for fp in floor_plans:
                lo = fp.bbox[bbox_axis_idx]
                hi = fp.bbox[bbox_axis_idx + 2]
                if c_axis < lo:
                    d = lo - c_axis
                elif c_axis > hi:
                    d = c_axis - hi
                else:
                    d = 0.0
                if d < best_dist:
                    best_dist = d
                    best = fp
            chosen = best
        if chosen:
            el.floor_label = chosen.label
            el.floor_index = chosen.index
            el.plan_index = chosen.index
            chosen.elements.append(el)
        else:
            unassigned.append(el)

    logger.info(
        "Plan-kat ataması: %d plan, %d eleman atandi, %d atanamadi",
        len(floor_plans),
        sum(len(p.elements) for p in floor_plans),
        len(unassigned),
    )
    return floor_plans, unassigned
