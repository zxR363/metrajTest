"""Faz 1: Katman bazli geometri/entity istatistikleri.

``layer_detection.score_layer`` icin sinyaller toplar. Saf regex tek-sinyalden
cikip su kanallari birlikte kullanmamizi saglar:

* **Ad** (regex / token Jaccard / signal_hints alias listesi) — ``layer_detection``.
* **Renk** (ACI kodu; signal_hints icindeki ``color_hints`` ile esleme).
* **Entity dagilimi** (kapali poly / hatch / blok / cizgi orani).
* **Alan & aspect ratio** istatistikleri (kolon kucuk+kompakt, perde uzun+ince,
  doseme tek/birkac buyuk poligon).

Bu modul ``RawCadModel`` haricinde dis baglilik almaz; saf shapely + Python.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from ..cad_io.dxf_reader import RawCadModel


@dataclass
class LayerSignals:
    """Tek katmana ait sinyallerin paketi.

    ``area_*`` ve ``aspect_*`` istatistikleri **yalnizca kapali polyline'lar
    ve hatch boundary'leri** uzerinden hesaplanir (acik polyline'lar / line'lar
    "alan" tasimaz). Eger katmanda kapali geometri yoksa bu alanlar ``None``
    olarak kalir.
    """

    layer: str
    color: int = 7
    poly_closed_count: int = 0
    poly_open_count: int = 0
    hatch_count: int = 0
    block_count: int = 0
    line_count: int = 0
    text_count: int = 0
    #: kapali poly + hatch toplam sayisi (skorlayicida "alan tasiyici" sinyal)
    closed_geom_count: int = 0
    area_min: float = 0.0
    area_max: float = 0.0
    area_median: float = 0.0
    aspect_min: float = 1.0
    aspect_max: float = 1.0
    aspect_median: float = 1.0
    #: kapali geometrilerden cikan toplam uzunluk (acik polyline + line uzunlugu
    #: ayrica ``open_total_length`` icinde tutulur)
    open_total_length: float = 0.0
    #: ortalama poligon kosegen uzunlugu (kolon ~0.5-1.0m, kiriş ~3-10m gibi)
    diagonal_median: float = 0.0
    notes: List[str] = field(default_factory=list)


def _polyline_area_perimeter(points: List[Tuple[float, float]]) -> Tuple[float, float]:
    """Shoelace alan + perimetre."""
    if len(points) < 3:
        return 0.0, 0.0
    n = len(points)
    s = 0.0
    p = 0.0
    for i in range(n):
        x0, y0 = points[i]
        x1, y1 = points[(i + 1) % n]
        s += x0 * y1 - x1 * y0
        p += math.hypot(x1 - x0, y1 - y0)
    return abs(s) * 0.5, p


def _bbox(points: List[Tuple[float, float]]) -> Tuple[float, float, float, float]:
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def _aspect_ratio_from_bbox(bbox: Tuple[float, float, float, float]) -> float:
    w = max(bbox[2] - bbox[0], 0.0)
    h = max(bbox[3] - bbox[1], 0.0)
    short = min(w, h)
    long = max(w, h)
    if short < 1e-9:
        return float("inf") if long > 0 else 1.0
    return long / short


def _safe_median(values: List[float]) -> float:
    if not values:
        return 0.0
    return float(statistics.median(values))


def collect_layer_signals(model: RawCadModel) -> Dict[str, LayerSignals]:
    """``RawCadModel`` -> her katman icin ``LayerSignals``.

    Bos katmanlar da sonuca dahil edilir (sayim 0); skorlayici bunlari ayri
    isaretler (genelde "0" / "Defpoints" gibi sistem katmanlari).
    """
    out: Dict[str, LayerSignals] = {}
    for lay in model.layers:
        out[lay] = LayerSignals(layer=lay, color=model.layer_colors.get(lay, 7))

    # Per-layer geometrik birikim
    areas: Dict[str, List[float]] = {}
    aspects: Dict[str, List[float]] = {}
    diagonals: Dict[str, List[float]] = {}

    def _ensure(layer: str) -> LayerSignals:
        if layer not in out:
            out[layer] = LayerSignals(layer=layer, color=model.layer_colors.get(layer, 7))
        return out[layer]

    for pl in model.polylines:
        s = _ensure(pl.layer)
        if pl.closed and len(pl.points) >= 3:
            s.poly_closed_count += 1
            area, _ = _polyline_area_perimeter(pl.points)
            bbox = _bbox(pl.points)
            asp = _aspect_ratio_from_bbox(bbox)
            diag = math.hypot(bbox[2] - bbox[0], bbox[3] - bbox[1])
            areas.setdefault(pl.layer, []).append(area)
            if math.isfinite(asp):
                aspects.setdefault(pl.layer, []).append(asp)
            diagonals.setdefault(pl.layer, []).append(diag)
        else:
            s.poly_open_count += 1
            s.open_total_length += pl.length()
    for h in model.hatches:
        s = _ensure(h.layer)
        s.hatch_count += 1
        if len(h.boundary) >= 3:
            area, _ = _polyline_area_perimeter(h.boundary)
            bbox = _bbox(h.boundary)
            asp = _aspect_ratio_from_bbox(bbox)
            diag = math.hypot(bbox[2] - bbox[0], bbox[3] - bbox[1])
            areas.setdefault(h.layer, []).append(area)
            if math.isfinite(asp):
                aspects.setdefault(h.layer, []).append(asp)
            diagonals.setdefault(h.layer, []).append(diag)
    for b in model.blocks:
        _ensure(b.layer).block_count += 1
    for ln in model.lines:
        s = _ensure(ln.layer)
        s.line_count += 1
        s.open_total_length += ln.length()
    for t in model.texts:
        _ensure(t.layer).text_count += 1

    for layer, sig in out.items():
        sig.closed_geom_count = sig.poly_closed_count + sig.hatch_count
        a = areas.get(layer) or []
        asp = aspects.get(layer) or []
        d = diagonals.get(layer) or []
        if a:
            sig.area_min = float(min(a))
            sig.area_max = float(max(a))
            sig.area_median = _safe_median(a)
        if asp:
            sig.aspect_min = float(min(asp))
            sig.aspect_max = float(max(asp))
            sig.aspect_median = _safe_median(asp)
        if d:
            sig.diagonal_median = _safe_median(d)
    return out
