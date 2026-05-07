"""Eleman boyutuna gore yeniden siniflandirma.

DWG'de cogu zaman:
- KOLON NA katmanina asansor perdeleri / baca ayaklari da cizilir; bunlar
  PERDE veya ASANSOR olarak yeniden etiketlenmelidir.
- Kucuk PERDE polygonlari aslinda kolon-perde birlesim parcalaridir.

Heuristik: perimetre ve aspect ratio.
"""
from __future__ import annotations

import logging
from typing import List, Sequence

from shapely.geometry import Polygon

from .elements import StructuralElement

logger = logging.getLogger(__name__)


def _aspect_ratio(geom) -> float:
    try:
        mrr = geom.minimum_rotated_rectangle
        coords = list(mrr.exterior.coords)
        if len(coords) < 4:
            return 1.0
        edges = [
            ((coords[i+1][0]-coords[i][0])**2 + (coords[i+1][1]-coords[i][1])**2)**0.5
            for i in range(len(coords)-1)
        ]
        long_e = max(edges)
        short_e = min(edges)
        return long_e / max(short_e, 0.001)
    except Exception:
        return 1.0


def _max_dimension(geom) -> float:
    """Polygonun maksimum eksen boyutu (en uzun yon)."""
    try:
        xs = [pt[0] for pt in geom.exterior.coords]
        ys = [pt[1] for pt in geom.exterior.coords]
        return max(max(xs) - min(xs), max(ys) - min(ys))
    except Exception:
        return 0.0


def reclassify_columns_to_walls(
    elements: Sequence[StructuralElement],
    column_max_perim_m: float = 4.0,
    column_max_dim_m: float = 1.5,
    wall_min_aspect: float = 2.0,
) -> List[StructuralElement]:
    """KOLON kind'li ama gercekte perde olan elemanlari shear_wall'a tasi.

    Kriterler (herhangi biri):
    - perim > column_max_perim_m (1.5x1.5'ten buyuk -> perde)
    - max_dim > column_max_dim_m (en uzun kenari 1.5m'den fazla)
    - aspect_ratio > wall_min_aspect (uzun-ince -> perde)
    """
    out: List[StructuralElement] = []
    moved_to_wall = 0
    for el in elements:
        if el.kind == "column" and isinstance(el.geom, Polygon):
            perim = el.perimeter_m
            mx = _max_dimension(el.geom)
            ar = _aspect_ratio(el.geom)
            if (perim > column_max_perim_m or
                mx > column_max_dim_m or
                ar > wall_min_aspect):
                el.kind = "shear_wall"
                el.notes.append(
                    f"reclassified column->wall (perim={perim:.2f}, "
                    f"max_dim={mx:.2f}, aspect={ar:.2f})"
                )
                moved_to_wall += 1
        out.append(el)
    if moved_to_wall:
        logger.info(
            "Reclassify: %d kolon polygonu PERDE'ye tasindi (boyut/aspect kriteri)",
            moved_to_wall,
        )
    return out


def union_slabs_per_plan(
    floor_elements: Sequence[StructuralElement],
    main_slab_min_area_m2: float = 50.0,
    iou_dedupe_threshold: float = 0.5,
) -> List[StructuralElement]:
    """Bir plan icindeki SLAB polygonlarini ana doseme + ek doseme'ye ayirir.

    1) Ayni plan icindeki SLAB'lar arasinda IoU >= iou_dedupe_threshold
       olanlar duplicate (cogu zaman mimari + statik versiyon ayni alan).
       En buyuk olan tutulur.
    2) Ana doseme'ler (alan >= main_slab_min_area_m2) union'lanir.
    3) Asansor/teras gibi kucuk dosemeler ayri tutulur.
    """
    from shapely.geometry import MultiPolygon, Polygon
    from shapely.ops import unary_union

    slabs_input = [el for el in floor_elements if el.kind == "slab" and isinstance(el.geom, Polygon)]
    others_input = [el for el in floor_elements if not (el.kind == "slab" and isinstance(el.geom, Polygon))]

    # 1) IoU-bazli dedupe (ayni plan icindeki yakin geometriler)
    deduped: List[StructuralElement] = []
    for s in sorted(slabs_input, key=lambda x: -x.area_m2):
        is_dupe = False
        for kept in deduped:
            try:
                inter = s.geom.intersection(kept.geom).area
                if inter <= 0:
                    continue
                uni = s.geom.union(kept.geom).area
                if uni > 0 and inter / uni >= iou_dedupe_threshold:
                    is_dupe = True
                    break
            except Exception:
                continue
        if not is_dupe:
            deduped.append(s)

    # 2) Ana ve ek dosemelere ayir
    main = [s for s in deduped if s.area_m2 >= main_slab_min_area_m2]
    extras = [s for s in deduped if s.area_m2 < main_slab_min_area_m2]
    out = list(others_input) + list(extras)
    if not main:
        return out
    if len(main) == 1:
        return out + [main[0]]

    # 3) Ana dosemeleri union'la (cogu zaman MultiPolygon olur cunku ayrik)
    try:
        merged = unary_union([m.geom for m in main])
        if isinstance(merged, Polygon):
            new = StructuralElement(
                kind="slab", layer=main[0].layer, geom=merged,
                area_m2=merged.area, perimeter_m=merged.length,
                length_m=0.0,
                floor_label=main[0].floor_label,
                floor_index=main[0].floor_index,
                plan_index=main[0].plan_index,
            )
            out.append(new)
        elif isinstance(merged, MultiPolygon):
            for poly in merged.geoms:
                out.append(StructuralElement(
                    kind="slab", layer=main[0].layer, geom=poly,
                    area_m2=poly.area, perimeter_m=poly.length,
                    length_m=0.0,
                    floor_label=main[0].floor_label,
                    floor_index=main[0].floor_index,
                    plan_index=main[0].plan_index,
                ))
        else:
            out.extend(main)
    except Exception:
        out.extend(main)
    return out


def deduplicate_overlapping_beams(
    floor_elements: Sequence[StructuralElement],
    iou_threshold: float = 0.35,
) -> List[StructuralElement]:
    """Ayni planda ust uste binen kiris polygonlarini (mimari+yapisal cift cizim)
    IoU ile teke indirger."""
    beams = [e for e in floor_elements if e.kind == "beam"]
    others = [e for e in floor_elements if e.kind != "beam"]
    if len(beams) < 2:
        return list(floor_elements)
    kept: List[StructuralElement] = []
    for b in sorted(beams, key=lambda x: -x.area_m2):
        is_dupe = False
        for k in kept:
            try:
                inter = b.geom.intersection(k.geom).area
                uni = b.geom.union(k.geom).area
                if uni > 0 and inter / uni >= iou_threshold:
                    is_dupe = True
                    break
            except Exception:
                continue
        if not is_dupe:
            kept.append(b)
    if len(kept) < len(beams):
        logger.info(
            "Kiris IoU dedupe: %d -> %d (plan bazinda)",
            len(beams), len(kept),
        )
    return others + kept


def remove_collinear_centroids(
    elements: Sequence[StructuralElement],
    tol_m: float = 0.05,
) -> List[StructuralElement]:
    """Centroid'leri nerdeyse cakisik olan ayni-kind elemanlari at.

    Foundation gibi tam ust uste cizilmis polygonlari teke indirger.
    """
    out: List[StructuralElement] = []
    by_kind = {}
    for el in elements:
        by_kind.setdefault(el.kind, []).append(el)
    for kind, lst in by_kind.items():
        kept_centroids = []
        for el in lst:
            try:
                c = el.geom.centroid
                cxy = (c.x, c.y)
            except Exception:
                cxy = (0.0, 0.0)
            duplicate = False
            for prev_xy in kept_centroids:
                dx = cxy[0] - prev_xy[0]
                dy = cxy[1] - prev_xy[1]
                if (dx * dx + dy * dy) ** 0.5 < tol_m:
                    duplicate = True
                    break
            if not duplicate:
                out.append(el)
                kept_centroids.append(cxy)
    return out
