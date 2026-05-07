"""Mahal (room) boundary detection.

Three fallback strategies, applied in order:

1. **Existing closed boundaries** -- if the project supplies polylines/hatches
   on the ``room_boundary`` role, use them directly.
2. **Wall polygonization** -- explode every wall line into segments, run
   ``shapely.ops.polygonize`` on the noded set and keep polygons that contain
   exactly one room label.
3. **Inverse hatch** -- take the bounding box of all walls, subtract a
   buffered union of wall segments and treat residual closed polygons as
   candidate rooms.

Each detected room is paired with a single label via nearest-neighbour search
(label point inside polygon, otherwise minimum distance).
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from shapely.geometry import LineString, MultiPolygon, Point, Polygon, box
from shapely.ops import polygonize, unary_union

from ..cad_io import RawCadModel
from ..cad_io.dxf_reader import CadPolyline, CadText
from ..mapping import LayerMap

logger = logging.getLogger(__name__)


# Mahal kodu duzeni: B-01, Z-12B, 1-04A, AZ-07, cati-01 ...
_ROOM_CODE_RE = re.compile(
    r"^\s*(?P<kat>B|AZ|Z|cati|[0-9])\s*[-_/]\s*(?P<no>\d{1,3}[A-Za-z]?)\s*$",
    re.IGNORECASE,
)


@dataclass
class Room:
    """Mahal listesi satirina kaynak teskil eden veri yapisi."""

    code: str  # B-01
    name: str  # KORIDOR
    floor: str  # B / Z / 1 / 2 / cati
    polygon: Polygon
    label_point: Tuple[float, float]
    height: float = 0.0
    floor_tip: Optional[str] = None  # DS3
    wall_tip: Optional[str] = None  # DV7
    ceiling_tip: Optional[str] = None  # TV2
    skirting_tip: Optional[str] = None  # SP_TER
    extras: Dict[str, str] = field(default_factory=dict)

    @property
    def area(self) -> float:
        return float(self.polygon.area)

    @property
    def perimeter(self) -> float:
        return float(self.polygon.length)

    def to_dict(self) -> Dict[str, object]:
        return {
            "code": self.code,
            "name": self.name,
            "floor": self.floor,
            "area": self.area,
            "perimeter": self.perimeter,
            "height": self.height,
            "floor_tip": self.floor_tip,
            "wall_tip": self.wall_tip,
            "ceiling_tip": self.ceiling_tip,
            "skirting_tip": self.skirting_tip,
            "label_point": self.label_point,
        }


@dataclass
class DetectionStats:
    strategy_counts: Dict[str, int] = field(default_factory=dict)
    unmatched_labels: List[str] = field(default_factory=list)
    polygons_without_label: int = 0


class RoomDetector:
    """Detect rooms from a :class:`RawCadModel` using a layer-role mapping."""

    def __init__(self, layer_map: LayerMap, default_height: float = 4.3,
                 wall_buffer: float = 0.001) -> None:
        self.layer_map = layer_map
        self.default_height = default_height
        self.wall_buffer = wall_buffer

    def detect(self, model: RawCadModel) -> Tuple[List[Room], DetectionStats]:
        labels = self._extract_labels(model)
        wall_lines = self._extract_walls(model)
        explicit_polys = self._extract_explicit_boundaries(model)

        polygons: List[Tuple[Polygon, str]] = []
        stats = DetectionStats()
        # Strategy 1: explicit polylines/hatches
        for poly in explicit_polys:
            polygons.append((poly, "explicit"))
        if polygons:
            stats.strategy_counts["explicit"] = len(polygons)

        # Strategy 2: wall polygonization
        if not polygons and wall_lines:
            for poly in self._polygonize_walls(wall_lines):
                polygons.append((poly, "wall_polygonize"))
            stats.strategy_counts["wall_polygonize"] = len(polygons)

        # Strategy 3: inverse hatch (last resort)
        if not polygons and wall_lines:
            for poly in self._inverse_hatch(wall_lines):
                polygons.append((poly, "inverse_hatch"))
            stats.strategy_counts["inverse_hatch"] = len(polygons)

        rooms: List[Room] = []
        used_labels: set[int] = set()
        for poly, strategy in polygons:
            if poly.is_empty or poly.area < 1e-3:
                continue
            label_idx = self._best_label_for_polygon(poly, labels, used_labels)
            if label_idx is None:
                stats.polygons_without_label += 1
                continue
            used_labels.add(label_idx)
            label = labels[label_idx]
            code, name, floor = self._parse_label(label.text)
            rooms.append(
                Room(
                    code=code,
                    name=name,
                    floor=floor,
                    polygon=poly,
                    label_point=label.insert,
                    height=self.default_height,
                )
            )
        for idx, lbl in enumerate(labels):
            if idx not in used_labels:
                stats.unmatched_labels.append(lbl.text)
        rooms.sort(key=lambda r: (r.floor, r.code))
        logger.info(
            "Detected %d rooms (strategies=%s, unmatched=%d, no_label=%d)",
            len(rooms),
            stats.strategy_counts,
            len(stats.unmatched_labels),
            stats.polygons_without_label,
        )
        return rooms, stats

    def _extract_labels(self, model: RawCadModel) -> List[CadText]:
        labels: List[CadText] = []
        for txt in model.texts:
            role = self.layer_map.role_of(txt.layer)
            if role == "room_label":
                labels.append(txt)
        return labels

    def _extract_walls(self, model: RawCadModel) -> List[LineString]:
        wall_lines: List[LineString] = []
        for line in model.lines:
            role = self.layer_map.role_of(line.layer)
            if role in {"wall", "wall_partition"}:
                wall_lines.append(LineString([line.start, line.end]))
        for poly in model.polylines:
            role = self.layer_map.role_of(poly.layer)
            if role in {"wall", "wall_partition"}:
                if len(poly.points) >= 2:
                    pts = list(poly.points)
                    if poly.closed and pts[0] != pts[-1]:
                        pts.append(pts[0])
                    for a, b in zip(pts, pts[1:]):
                        wall_lines.append(LineString([a, b]))
        return wall_lines

    def _extract_explicit_boundaries(self, model: RawCadModel) -> List[Polygon]:
        polys: List[Polygon] = []
        for poly in model.polylines:
            role = self.layer_map.role_of(poly.layer)
            if role == "room_boundary" and poly.closed and len(poly.points) >= 3:
                shp = Polygon(poly.points)
                if shp.is_valid and shp.area > 1e-3:
                    polys.append(shp)
        for hatch in model.hatches:
            role = self.layer_map.role_of(hatch.layer)
            if role == "room_boundary" and len(hatch.boundary) >= 3:
                shp = Polygon(hatch.boundary)
                if shp.is_valid and shp.area > 1e-3:
                    polys.append(shp)
        return polys

    def _polygonize_walls(self, walls: Sequence[LineString]) -> List[Polygon]:
        if not walls:
            return []
        merged = unary_union(walls)
        polygons = list(polygonize(merged))
        return [p for p in polygons if p.area > 1e-3]

    def _inverse_hatch(self, walls: Sequence[LineString]) -> List[Polygon]:
        if not walls:
            return []
        merged = unary_union(walls)
        bbox = box(*merged.bounds).buffer(0.5)
        wall_strip = merged.buffer(self.wall_buffer)
        residual = bbox.difference(wall_strip)
        polys: List[Polygon] = []
        if isinstance(residual, Polygon):
            polys.append(residual)
        elif isinstance(residual, MultiPolygon):
            polys.extend(residual.geoms)
        # Drop the outer/exterior polygon (largest) which represents the world.
        polys.sort(key=lambda p: p.area, reverse=True)
        if polys:
            polys = polys[1:]
        return [p for p in polys if p.area > 1.0]

    def _best_label_for_polygon(
        self, polygon: Polygon, labels: Sequence[CadText], used: set[int]
    ) -> Optional[int]:
        # Prefer labels strictly inside the polygon
        for idx, lbl in enumerate(labels):
            if idx in used:
                continue
            if polygon.contains(Point(lbl.insert)):
                return idx
        # Otherwise pick the closest label within reasonable proximity
        best_idx: Optional[int] = None
        best_dist = float("inf")
        for idx, lbl in enumerate(labels):
            if idx in used:
                continue
            d = polygon.distance(Point(lbl.insert))
            if d < best_dist:
                best_dist = d
                best_idx = idx
        # Reject labels that are too far away (outside reasonable threshold)
        if best_idx is not None and best_dist > polygon.length * 0.25:
            return None
        return best_idx

    @staticmethod
    def _parse_label(text: str) -> Tuple[str, str, str]:
        """Split a free-form label like "B-01\\nKORIDOR" into (code, name, floor)."""
        if not text:
            return "", "", ""
        lines = [ln.strip() for ln in re.split(r"[\n\r]+", text) if ln.strip()]
        code = ""
        name_parts: List[str] = []
        floor = ""
        for line in lines:
            match = _ROOM_CODE_RE.match(line.replace(" ", ""))
            if match and not code:
                code = f"{match.group('kat').upper()}-{match.group('no').upper()}"
                floor = match.group("kat").upper()
            else:
                name_parts.append(line)
        if not code and lines:
            # fallback: treat first token as code, rest as name
            tokens = lines[0].split()
            code = tokens[0]
            name_parts = (tokens[1:] + lines[1:]) if len(tokens) > 1 else lines[1:]
        return code, " ".join(name_parts).strip(), floor
