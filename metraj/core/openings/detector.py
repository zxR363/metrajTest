"""Door / window / opening extraction and minha (deduction) computation."""
from __future__ import annotations

import logging
import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from shapely.geometry import LineString, Point, Polygon

from ..cad_io import RawCadModel
from ..cad_io.dxf_reader import CadBlockRef
from ..mapping import LayerMap, ProjectConfig
from ..rooms import Room

logger = logging.getLogger(__name__)


# Heuristic dimension extraction from block names like "KAPI_100x240" / "WINDOW-150X120"
_NAME_DIM_RE = re.compile(r"(\d{2,4})\s*[xX_*]\s*(\d{2,4})")
# Door types that come from text/attribute "EN" or "WIDTH"
_DOOR_ATTR_KEYS = ("EN", "WIDTH", "GENISLIK", "EN_CM")
_HEIGHT_ATTR_KEYS = ("YUKSEKLIK", "HEIGHT", "BOY", "Y", "H")


@dataclass
class Opening:
    kind: str  # "door" | "window" | "internal"
    block_name: str
    room_code: Optional[str]
    floor: Optional[str]
    width_m: float
    height_m: float
    insert: Tuple[float, float]
    rotation: float = 0.0
    tip_label: str = ""

    @property
    def area(self) -> float:
        return self.width_m * self.height_m

    @property
    def dim_label(self) -> str:
        return f"{int(round(self.width_m * 100))}/{int(round(self.height_m * 100))}"


@dataclass
class OpeningSummary:
    """Per-floor / per-dimension counts used to populate the ``minha`` sheet."""

    by_floor_dim: Dict[Tuple[str, str], List[Opening]] = field(default_factory=dict)
    unassigned: List[Opening] = field(default_factory=list)


class OpeningDetector:
    """Resolve door/window block references against detected rooms."""

    def __init__(
        self,
        layer_map: LayerMap,
        project: ProjectConfig,
    ) -> None:
        self.layer_map = layer_map
        self.project = project

    def detect(self, model: RawCadModel, rooms: Sequence[Room]) -> List[Opening]:
        out: List[Opening] = []
        for block in model.blocks:
            kind = self._classify(block)
            if kind is None:
                continue
            width, height = self._extract_dimensions(block)
            if width <= 0 or height <= 0:
                continue
            width = self._snap(width, self.project.kapi_yuvarlama_cm if kind == "door"
                               else self.project.pencere_yuvarlama_cm)
            height = self._snap(height, self.project.kapi_yuvarlama_cm if kind == "door"
                                else self.project.pencere_yuvarlama_cm)
            room = self._assign_room(block, rooms)
            out.append(
                Opening(
                    kind=kind,
                    block_name=block.name,
                    room_code=room.code if room else None,
                    floor=room.floor if room else None,
                    width_m=width,
                    height_m=height,
                    insert=block.insert,
                    rotation=block.rotation,
                    tip_label=self._tip_label(block, kind),
                )
            )
        logger.info(
            "Detected %d openings (doors=%d, windows=%d, internal=%d)",
            len(out),
            sum(1 for o in out if o.kind == "door"),
            sum(1 for o in out if o.kind == "window"),
            sum(1 for o in out if o.kind == "internal"),
        )
        return out

    @staticmethod
    def summary(openings: Sequence[Opening]) -> OpeningSummary:
        s = OpeningSummary()
        for opening in openings:
            if not opening.floor:
                s.unassigned.append(opening)
                continue
            key = (opening.floor, opening.dim_label)
            s.by_floor_dim.setdefault(key, []).append(opening)
        return s

    @staticmethod
    def total_minha_area(openings: Sequence[Opening]) -> float:
        return sum(o.area for o in openings if o.kind in {"door", "window"})

    def _classify(self, block: CadBlockRef) -> Optional[str]:
        role = self.layer_map.role_of(block.layer)
        name_upper = block.name.upper()
        if role == "door" or "KAPI" in name_upper or "DOOR" in name_upper:
            return "door"
        if role == "window" or "PENCERE" in name_upper or "WINDOW" in name_upper or "GLAZ" in name_upper:
            return "window"
        if role == "opening_internal":
            return "internal"
        return None

    def _extract_dimensions(self, block: CadBlockRef) -> Tuple[float, float]:
        # 1) Attributes (KAPI BLOK with EN/YUKSEKLIK attribs)
        width = self._first_numeric(block.attribs, _DOOR_ATTR_KEYS)
        height = self._first_numeric(block.attribs, _HEIGHT_ATTR_KEYS)
        # 2) Dynamic block parameters
        if width is None:
            width = self._first_numeric(block.dynamic_params, _DOOR_ATTR_KEYS)
        if height is None:
            height = self._first_numeric(block.dynamic_params, _HEIGHT_ATTR_KEYS)
        # 3) Block name pattern: KAPI_100x240
        if width is None or height is None:
            m = _NAME_DIM_RE.search(block.name)
            if m:
                w_cm, h_cm = int(m.group(1)), int(m.group(2))
                if width is None:
                    width = w_cm / 100.0
                if height is None:
                    height = h_cm / 100.0
        # 4) Scale factor fallback: assume base block is 1m wide
        if width is None and block.scale[0] != 0:
            width = abs(block.scale[0])
        if height is None:
            height = 2.4 if "KAPI" in block.name.upper() or "DOOR" in block.name.upper() else 1.5
        # Convert any value larger than 10 (assumed cm) to m
        if width and width > 10:
            width = width / 100.0
        if height and height > 10:
            height = height / 100.0
        return float(width or 0.0), float(height or 0.0)

    @staticmethod
    def _first_numeric(source: Dict[str, str], keys: Sequence[str]) -> Optional[float]:
        for key in keys:
            if key in source:
                try:
                    return float(str(source[key]).replace(",", "."))
                except ValueError:
                    continue
        # case-insensitive fallback
        upper = {k.upper(): v for k, v in source.items()}
        for key in keys:
            if key.upper() in upper:
                try:
                    return float(str(upper[key.upper()]).replace(",", "."))
                except ValueError:
                    continue
        return None

    def _snap(self, value: float, snap_cm: float) -> float:
        if snap_cm <= 0:
            return value
        snap = snap_cm / 100.0
        return round(round(value / snap) * snap, 3)

    def _assign_room(self, block: CadBlockRef, rooms: Sequence[Room]) -> Optional[Room]:
        if not rooms:
            return None
        pt = Point(block.insert)
        # Closest containing room
        for room in rooms:
            if room.polygon.contains(pt):
                return room
        # Otherwise the room whose boundary is closest (within ~1m)
        nearest = min(rooms, key=lambda r: r.polygon.distance(pt))
        if nearest.polygon.distance(pt) <= 1.0:
            return nearest
        return None

    def _tip_label(self, block: CadBlockRef, kind: str) -> str:
        for key in ("TIP", "TYPE", "TIP_NO"):
            if key in block.attribs:
                return block.attribs[key]
        return f"{kind.upper()}-{block.name[:8]}"
