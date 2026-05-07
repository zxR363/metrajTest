"""Wall extraction: 2D plan -> wall segments with type, length and (estimated) height.

Each architectural layer can map to a wall *type* (tugla 19, gazbeton 20,
alcipanel 10 ...).  We approximate wall thickness from the layer role tag
``wall@thickness=N`` or from the ``layer_thickness`` mapping, falling back to
20 cm.
"""
from __future__ import annotations

import logging
import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from shapely.geometry import LineString, MultiLineString
from shapely.ops import linemerge, unary_union

from ..cad_io import RawCadModel
from ..mapping import LayerMap, ProjectConfig

logger = logging.getLogger(__name__)


_DEFAULT_THICKNESS_CM: Dict[str, float] = {
    "DUVAR_H_0.10": 10.0,
    "DUVAR_H_0.15": 15.0,
    "DUVAR_H_0.20": 20.0,
    "DUVAR_H_0.25": 25.0,
    "DUVAR_H_0.30": 30.0,
}

_THICKNESS_FROM_LAYER_RE = re.compile(r"(\d{2,3})", re.IGNORECASE)


@dataclass
class WallSegment:
    layer: str
    thickness_m: float
    length_m: float
    geom: LineString
    height_m: float = 0.0
    floor: Optional[str] = None

    @property
    def area_m2(self) -> float:
        return self.length_m * self.height_m

    @property
    def thickness_band(self) -> str:
        rounded = round(self.thickness_m, 2)
        return f"DUVAR_H_{rounded:.2f}"


@dataclass
class WallTotals:
    """Aggregated wall metrics ready to populate the ``minha`` sheet."""

    by_band_length: Dict[str, float] = field(default_factory=lambda: defaultdict(float))
    by_band_area: Dict[str, float] = field(default_factory=lambda: defaultdict(float))
    by_floor_band: Dict[Tuple[str, str], float] = field(default_factory=lambda: defaultdict(float))


class WallExtractor:
    """Extract wall segments from the model and aggregate them."""

    def __init__(
        self,
        layer_map: LayerMap,
        project: ProjectConfig,
        thickness_overrides: Optional[Mapping[str, float]] = None,
        default_height: float = 4.3,
    ) -> None:
        self.layer_map = layer_map
        self.project = project
        self.thickness_overrides = dict(thickness_overrides or {})
        self.default_height = default_height

    def extract(self, model: RawCadModel) -> List[WallSegment]:
        segments: List[WallSegment] = []
        # Aggregate by layer so we can call linemerge once per layer (faster +
        # more accurate length when collinear segments are present).
        by_layer: Dict[str, List[LineString]] = defaultdict(list)
        for line in model.lines:
            role = self.layer_map.role_of(line.layer)
            if role in {"wall", "wall_partition"}:
                by_layer[line.layer].append(LineString([line.start, line.end]))
        for poly in model.polylines:
            role = self.layer_map.role_of(poly.layer)
            if role in {"wall", "wall_partition"} and len(poly.points) >= 2:
                pts = list(poly.points)
                if poly.closed and pts[0] != pts[-1]:
                    pts.append(pts[0])
                for a, b in zip(pts, pts[1:]):
                    by_layer[poly.layer].append(LineString([a, b]))

        for layer, lines in by_layer.items():
            thickness = self._thickness_for_layer(layer)
            if not lines:
                continue
            try:
                union = unary_union(lines)
                if isinstance(union, LineString):
                    merged = union
                else:
                    merged = linemerge(union)
            except (ValueError, TypeError) as exc:
                logger.debug("linemerge failed for layer %s (%s); using raw lines", layer, exc)
                merged = MultiLineString(lines)
            segs: List[LineString] = []
            if isinstance(merged, LineString):
                segs.append(merged)
            elif isinstance(merged, MultiLineString):
                segs.extend(merged.geoms)
            for ls in segs:
                segments.append(
                    WallSegment(
                        layer=layer,
                        thickness_m=thickness,
                        length_m=ls.length,
                        geom=ls,
                        height_m=self.default_height,
                    )
                )
        logger.info("Extracted %d wall segments across %d layers", len(segments), len(by_layer))
        return segments

    def aggregate(self, segments: Sequence[WallSegment]) -> WallTotals:
        totals = WallTotals()
        for seg in segments:
            band = seg.thickness_band
            totals.by_band_length[band] += seg.length_m
            totals.by_band_area[band] += seg.area_m2
            if seg.floor:
                totals.by_floor_band[(seg.floor, band)] += seg.area_m2
        return totals

    def _thickness_for_layer(self, layer: str) -> float:
        if layer in self.thickness_overrides:
            return float(self.thickness_overrides[layer])
        # Try to extract from layer name suffix: "DUVAR-19" -> 0.19m
        m = _THICKNESS_FROM_LAYER_RE.search(layer)
        if m:
            cm = int(m.group(1))
            if 5 <= cm <= 80:
                return cm / 100.0
        # default: 20 cm
        return 0.20
