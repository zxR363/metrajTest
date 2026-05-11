"""Yapisal eleman teshis (diagnostics) JSON dokumu.

Faz 1+ adimlarinda (katman skorlayicisi, geometrik siniflandirici, profile fitter)
referans olarak kullanilacak yapilandirilmis cikis. Her eleman icin:

* ``kind`` (autodetect kararina gore sinif)
* ``layer`` (DXF katman adi)
* ``floor_label`` (atanmis kat)
* ``geom_type``, ``area_m2``, ``perimeter_m``, ``length_m``
* ``bbox``, ``centroid``, ``aspect_ratio``
* ``source_entity_type`` (LWPOLYLINE / HATCH / LINE / INSERT bilinmiyorsa Polygon / LineString)

Pipeline cikisi ile birlikte ``elements_diagnostics.json`` olarak yazilir;
benchmark scripti ve gelecek (Faz 1) ML/heuristic siniflandiricilar bunu ortak
girdi olarak kullanir.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from shapely.geometry import LineString, MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry

from .elements import StructuralElement, StructuralModel


@dataclass
class ElementDiagnostic:
    """Tek eleman teshis kaydi (JSON-serilestirilebilir)."""

    kind: str
    layer: str
    geom_type: str
    floor_label: Optional[str]
    plan_index: Optional[int]
    area_m2: float
    perimeter_m: float
    length_m: float
    bbox: Tuple[float, float, float, float]
    centroid: Tuple[float, float]
    #: ``long_edge / short_edge`` (bbox tabanli kaba olcum); kolon/perde
    #: ayriminda heuristik sinyal. Cember/duzgun karelerde 1.0.
    aspect_ratio: float
    #: Polygon/MultiPolygon/LineString'in altinda yatan kaynak.  Faz 1'de
    #: ``hash_dedupe_by_geometry`` oncesi entity tipini buraya tasiyabiliriz.
    source_entity_type: str
    #: Faz 3: ``geometric_classify`` cikisi (layer-bagimsiz tahmin). ``kind`` ile
    #: farkli olabilir; UI bunu "kuskulu" olarak isaretler.
    geometric_kind: Optional[str] = None
    geometric_confidence: float = 0.0
    geometric_reason: str = ""
    properties: Dict[str, float] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)


def _geom_type(g: BaseGeometry) -> str:
    if isinstance(g, Polygon):
        return "Polygon"
    if isinstance(g, MultiPolygon):
        return "MultiPolygon"
    if isinstance(g, LineString):
        return "LineString"
    return type(g).__name__


def _bbox(g: BaseGeometry) -> Tuple[float, float, float, float]:
    try:
        x0, y0, x1, y1 = g.bounds
        return (float(x0), float(y0), float(x1), float(y1))
    except Exception:
        return (0.0, 0.0, 0.0, 0.0)


def _centroid(g: BaseGeometry) -> Tuple[float, float]:
    try:
        c = g.centroid
        return (float(c.x), float(c.y))
    except Exception:
        return (0.0, 0.0)


def _aspect_ratio(bbox: Tuple[float, float, float, float]) -> float:
    w = max(bbox[2] - bbox[0], 0.0)
    h = max(bbox[3] - bbox[1], 0.0)
    short = min(w, h)
    long = max(w, h)
    if short < 1e-9:
        return float("inf") if long > 0 else 1.0
    return long / short


def diagnose_element(el: StructuralElement) -> ElementDiagnostic:
    bbox = _bbox(el.geom)
    # Faz 3: layer-bagimsiz geometric_classify ekle (geri uyumlu, varsayilan esikler).
    from .classify import geometric_classify  # circular import koruma
    gc = geometric_classify(el)
    return ElementDiagnostic(
        kind=str(el.kind),
        layer=str(el.layer),
        geom_type=_geom_type(el.geom),
        floor_label=el.floor_label,
        plan_index=el.plan_index,
        area_m2=float(el.area_m2),
        perimeter_m=float(el.perimeter_m),
        length_m=float(el.length_m),
        bbox=bbox,
        centroid=_centroid(el.geom),
        aspect_ratio=_aspect_ratio(bbox),
        source_entity_type=_geom_type(el.geom),
        geometric_kind=gc.kind,
        geometric_confidence=float(gc.confidence),
        geometric_reason=gc.reason,
        properties={str(k): float(v) for k, v in (el.properties or {}).items()},
        notes=list(el.notes or []),
    )


def diagnose_model(smodel: StructuralModel) -> Dict[str, Any]:
    """``StructuralModel`` -> JSON-uyumlu sozluk.

    Top-level alanlar:
      * ``floors``: kat etiketi -> eleman listesi
      * ``unassigned``: kat'a atanmayan elemanlar
      * ``summary``: kind -> sayim
    """
    floors: List[Dict[str, Any]] = []
    summary: Dict[str, int] = {}

    for fp in smodel.floors:
        diags = [asdict(diagnose_element(e)) for e in fp.elements]
        for d in diags:
            summary[d["kind"]] = summary.get(d["kind"], 0) + 1
        floors.append({
            "label": fp.label,
            "index": fp.index,
            "elevation_m": fp.elevation_m,
            "storey_height_m": fp.storey_height_m,
            "bbox": list(fp.bbox),
            "multiplier": fp.multiplier,
            "extra_labels": list(fp.extra_labels),
            "element_count": len(diags),
            "elements": diags,
        })

    unassigned = [asdict(diagnose_element(e)) for e in smodel.unassigned]
    for d in unassigned:
        summary[d["kind"]] = summary.get(d["kind"], 0) + 1

    return {
        "schema_version": 1,
        "floor_count": len(floors),
        "element_total": sum(f["element_count"] for f in floors) + len(unassigned),
        "summary_by_kind": summary,
        "floors": floors,
        "unassigned": unassigned,
    }


def write_diagnostics_json(smodel: StructuralModel, path: str | Path) -> Path:
    """Diagnostics JSON'u disk'e yazar. Donus: yazilan ``Path``."""
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = diagnose_model(smodel)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    return out_path
