"""Eleman boyutuna gore yeniden siniflandirma + Faz 3 geometric_classify.

DWG'de cogu zaman:
- KOLON NA katmanina asansor perdeleri / baca ayaklari da cizilir; bunlar
  PERDE veya ASANSOR olarak yeniden etiketlenmelidir.
- Kucuk PERDE polygonlari aslinda kolon-perde birlesim parcalaridir.

Heuristik: perimetre ve aspect ratio.

Faz 3:
* ``GeometricThresholds`` — alan/aspect ratio esikleri (config'den override).
* ``geometric_classify(element, thresholds)`` — katman bilgisi olmadan geometriden
  ElementKind tahmini (kolon < 2.5 aspect, perde >= 8.0, dosememe alan > 50 m2).
* ``find_classification_conflicts(elements)`` — layer_kind ile geometric_kind
  uyusmazligi olanlari uyari listesi olarak doner; sessiz overwrite YAPMAZ.
* ``LineString`` (acik LINE/polyline) kirislerinde ``geom.length`` dogrudan
  ele alinir.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence

from shapely.geometry import LineString, Polygon
from shapely.geometry.base import BaseGeometry

from .elements import StructuralElement

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Faz 3: Geometric classification
# ---------------------------------------------------------------------------


@dataclass
class GeometricThresholds:
    """Geometriden ElementKind tahmini icin sabit esikler.

    Tum esikler config'den (``geometric_thresholds: {...}``) override edilebilir.
    Varsayilanlar Kumluca elemanlarinda gozlemlenen aralıklara dayanir
    (bkz. ``build/bench_phase0/calibrated/elements_diagnostics.json``).
    """

    #: Aspect ratio < column_max: kompakt eleman -> kolon adayi.
    column_max_aspect: float = 2.5
    #: column_max < aspect < wall_min: belirsiz (kuskulu); ne kolon ne perde.
    wall_min_aspect: float = 8.0
    #: Kolon alani genelde 0.05..5 m^2 araliginda (Kumluca medyan ~0.20).
    column_max_area_m2: float = 5.0
    #: Perde polygonu da kucuk-orta alanli olabilir; cok buyukse perde degildir.
    wall_max_area_m2: float = 50.0
    #: Doseme/temel/grobeton: buyuk alan.
    slab_min_area_m2: float = 30.0
    #: Temel polygonu cogu zaman tek/iki adet ve doseme'den belirgin buyuk olur;
    #: 200 m^2 esigi: 150 m^2 doseme, 300 m^2 radye temel ayrimini saglar.
    foundation_min_area_m2: float = 200.0
    #: Acik LINE veya LineString: kiris adayi.
    beam_min_length_m: float = 1.0
    #: Geometrik ayrim icin minimum kabul confidence (0..1). Daha dusukse
    #: "kuskulu" doner.
    min_confidence: float = 0.5

    @classmethod
    def from_dict(cls, data: Optional[Mapping[str, Any]]) -> "GeometricThresholds":
        if not data:
            return cls()
        kwargs: Dict[str, Any] = {}
        for fld in cls.__dataclass_fields__:
            if fld in data:
                try:
                    kwargs[fld] = float(data[fld])
                except (TypeError, ValueError):
                    continue
        return cls(**kwargs)


@dataclass
class GeometricClassification:
    """``geometric_classify`` sonucu."""

    #: Tahmin edilen kind (kolon/perde/doseme/temel/kiris); None = belirsiz.
    kind: Optional[str]
    #: 0..1 arasi guven; ``min_confidence`` altinda ise pratikte kuskulu.
    confidence: float
    #: Insan-okunabilir gerekce ("aspect=12.5>=wall_min").
    reason: str


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


def geometric_classify(
    element: StructuralElement,
    thresholds: Optional[GeometricThresholds] = None,
) -> GeometricClassification:
    """Bir elemanin geometrisinden olasi ElementKind'i tahmin eder.

    Katman bilgisi KULLANILMAZ — tamamen alan/aspect/geom tipi sinyalleriyle
    karar verir. Hibrit kontrolde (``find_classification_conflicts``) bu sonuc
    layer-based ``element.kind`` ile karsilastirilir; uyusmazlik UYARI olarak
    raporlanir, sessiz overwrite yapilmaz.

    Hierarsi:
      1. Acik LINE / LineString -> beam (kiris).
      2. Polygon (closed):
         - alan >= foundation_min_area_m2 ve aspect < column_max -> foundation/slab
           (alan >= 200 m2 -> foundation, degilse -> slab).
         - aspect >= wall_min_aspect ve alan < wall_max_area_m2 -> shear_wall.
         - aspect < column_max_aspect ve alan < column_max_area_m2 -> column.
         - alan >= slab_min_area_m2 ve aspect < column_max -> slab.
         - aksi durumda kuskulu (None, confidence < min_confidence).

    Confidence: aspect/area esiklerinden uzaklik bazli kaba bir 0..1 skor.
    """
    th = thresholds or GeometricThresholds()

    geom: BaseGeometry = element.geom

    # 1) Acik LINE / LineString -> kiris adayi
    if isinstance(geom, LineString):
        length = element.length_m if element.length_m > 0 else float(geom.length)
        if length >= th.beam_min_length_m:
            # Confidence: 0.6..1.0 (uzunluk arttikca artar)
            conf = min(1.0, 0.6 + length / 50.0)
            return GeometricClassification(
                kind="beam", confidence=conf,
                reason=f"open_line length={length:.2f}m>={th.beam_min_length_m}",
            )
        return GeometricClassification(
            kind=None, confidence=0.2,
            reason=f"open_line length={length:.2f}m<{th.beam_min_length_m} (kuskulu)",
        )

    if not isinstance(geom, Polygon):
        return GeometricClassification(
            kind=None, confidence=0.0, reason=f"unsupported_geom={type(geom).__name__}",
        )

    area = element.area_m2 if element.area_m2 > 0 else float(geom.area)
    asp = _aspect_ratio(geom)

    # 2a) Cok buyuk + kompakt -> temel veya doseme
    if area >= th.foundation_min_area_m2 and asp < th.column_max_aspect:
        return GeometricClassification(
            kind="foundation", confidence=0.85,
            reason=f"big_compact area={area:.1f}>={th.foundation_min_area_m2} "
                   f"aspect={asp:.2f}<{th.column_max_aspect}",
        )

    # 2b) Uzun-ince -> perde
    if asp >= th.wall_min_aspect and area < th.wall_max_area_m2:
        # Confidence: aspect arttikca artar (8'de 0.7, 20'de ~0.95)
        conf = min(0.95, 0.6 + (asp - th.wall_min_aspect) / 30.0)
        return GeometricClassification(
            kind="shear_wall", confidence=conf,
            reason=f"long_thin aspect={asp:.2f}>={th.wall_min_aspect} area={area:.2f}",
        )

    # 2c) Kompakt + kucuk -> kolon
    if asp < th.column_max_aspect and area < th.column_max_area_m2:
        conf = max(0.6, 1.0 - asp / th.column_max_aspect * 0.3)
        return GeometricClassification(
            kind="column", confidence=conf,
            reason=f"compact_small area={area:.2f}<{th.column_max_area_m2} "
                   f"aspect={asp:.2f}<{th.column_max_aspect}",
        )

    # 2d) Orta-buyuk alan kompakt -> doseme
    if area >= th.slab_min_area_m2 and asp < th.column_max_aspect:
        return GeometricClassification(
            kind="slab", confidence=0.75,
            reason=f"medium_compact area={area:.1f}>={th.slab_min_area_m2} aspect={asp:.2f}",
        )

    # 2e) Belirsiz bolge (kolon-perde arasi)
    if th.column_max_aspect <= asp < th.wall_min_aspect:
        return GeometricClassification(
            kind=None, confidence=0.3,
            reason=f"uncertain {th.column_max_aspect}<=aspect={asp:.2f}<{th.wall_min_aspect}",
        )

    return GeometricClassification(
        kind=None, confidence=0.2,
        reason=f"no_match area={area:.2f} aspect={asp:.2f}",
    )


@dataclass
class ClassificationConflict:
    """``layer_kind`` ile ``geometric_kind`` uyusmazligi.

    Pipeline'da uyari listesine eklenir; sessiz overwrite yapilmaz — son karar
    yine ``element.kind``'tedir (layer-bazli). UI bunlari "kuskulu siniflandirma"
    listesinde gosterir; kullanici manuel override edebilir.
    """

    element_index: int
    layer: str
    layer_kind: str
    geometric_kind: Optional[str]
    confidence: float
    reason: str
    area_m2: float
    aspect_ratio: float


#: Geometri tek basina ayirt edemedigi dogal cifteler. Bu ciftlerden biri
#: layer-bazli, digeri geometri-bazli olursa conflict raporlanmaz — UI spam'i
#: onlemek icin. Faz 6 multi-reference learning bunu cozecek.
_NATURAL_AMBIGUITY_PAIRS = frozenset({
    frozenset({"beam", "shear_wall"}),
    frozenset({"slab", "foundation"}),
    frozenset({"slab", "roof_slab"}),
    frozenset({"foundation", "lean_concrete"}),
})


def find_classification_conflicts(
    elements: Sequence[StructuralElement],
    thresholds: Optional[GeometricThresholds] = None,
    *,
    min_confidence: Optional[float] = None,
) -> List[ClassificationConflict]:
    """Layer-bazli ve geometri-bazli sinif farkliysa uyari listesi doner.

    Yalnizca ``geometric_classify`` confidence'i ``min_confidence``'in (veya
    ``thresholds.min_confidence``) ustunde olan elemanlar uyari verir.
    Dogal-belirsizlik ciftleri (``_NATURAL_AMBIGUITY_PAIRS``) suppress edilir.
    """
    th = thresholds or GeometricThresholds()
    min_conf = th.min_confidence if min_confidence is None else min_confidence
    out: List[ClassificationConflict] = []
    for i, el in enumerate(elements):
        gc = geometric_classify(el, th)
        if gc.kind is None or gc.confidence < min_conf:
            continue
        if gc.kind == el.kind:
            continue
        # Bazi durumlar dogal uyusmazliktir: parapet/elevator_shaft/chimney
        # layer-bazli kabul edilir, geometri benzer olabilir; sessiz birak.
        if el.kind in {"parapet", "elevator_shaft", "chimney", "stair",
                       "protection", "lean_concrete", "roof_slab", "slab_opening"}:
            continue
        # Dogal belirsizlik (beam<->shear_wall, slab<->foundation): geometri
        # ayirt etmiyor; conflict listesi disi.
        if frozenset({el.kind, gc.kind}) in _NATURAL_AMBIGUITY_PAIRS:
            continue
        if isinstance(el.geom, Polygon):
            asp = _aspect_ratio(el.geom)
            area = el.area_m2
        else:
            asp = 0.0
            area = 0.0
        out.append(ClassificationConflict(
            element_index=i,
            layer=el.layer,
            layer_kind=str(el.kind),
            geometric_kind=gc.kind,
            confidence=gc.confidence,
            reason=gc.reason,
            area_m2=area,
            aspect_ratio=asp,
        ))
    return out


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
