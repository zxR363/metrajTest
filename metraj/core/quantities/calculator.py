"""Net quantity calculator.

For every detected room we compute:

* Net floor area    = polygon.area - column/shaft cutouts
* Net ceiling area  = same as floor (no acoustic add-ons here)
* Net wall area     = perimeter * height - door/window minha - duvar_genel_minha
* Net skirting len  = perimeter - door widths - sup_minha

The inputs are the room polygon + a list of per-room openings.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence

from ..openings import Opening
from ..rooms import Room

logger = logging.getLogger(__name__)


@dataclass
class RoomQuantities:
    room: Room
    net_floor_m2: float
    net_ceiling_m2: float
    net_wall_m2: float
    net_skirting_m: float
    door_count: int = 0
    window_count: int = 0
    door_minha_m2: float = 0.0
    window_minha_m2: float = 0.0
    door_width_total_m: float = 0.0
    floor_minha_m2: float = 0.0  # column / shaft cutouts
    ceiling_minha_m2: float = 0.0
    wall_minha_extra_m2: float = 0.0
    skirting_minha_m: float = 0.0


@dataclass
class QuantityOptions:
    skirting_height_m: float = 0.10  # 10 cm baseboard
    deduct_columns: bool = True
    floor_minha_overrides: Dict[str, float] = field(default_factory=dict)
    skirting_minha_overrides: Dict[str, float] = field(default_factory=dict)
    wall_minha_overrides: Dict[str, float] = field(default_factory=dict)


class QuantityCalculator:
    """Run the deduction logic per room."""

    def __init__(self, options: Optional[QuantityOptions] = None) -> None:
        self.options = options or QuantityOptions()

    def compute(
        self,
        rooms: Sequence[Room],
        openings: Sequence[Opening],
        column_polys: Optional[Sequence] = None,
    ) -> List[RoomQuantities]:
        # Index openings by room code
        per_room: Dict[str, List[Opening]] = {}
        for opening in openings:
            if opening.room_code:
                per_room.setdefault(opening.room_code, []).append(opening)

        results: List[RoomQuantities] = []
        for room in rooms:
            opes = per_room.get(room.code, [])
            doors = [o for o in opes if o.kind == "door"]
            windows = [o for o in opes if o.kind == "window"]
            door_minha = sum(o.area for o in doors)
            window_minha = sum(o.area for o in windows)
            door_width_total = sum(o.width_m for o in doors)

            floor_minha = self.options.floor_minha_overrides.get(room.code, 0.0)
            ceiling_minha = 0.0
            wall_minha_extra = self.options.wall_minha_overrides.get(room.code, 0.0)
            skirting_minha = self.options.skirting_minha_overrides.get(room.code, 0.0)

            if self.options.deduct_columns and column_polys:
                for col in column_polys:
                    if room.polygon.contains(col.centroid):
                        floor_minha += col.area
                        ceiling_minha += col.area

            net_floor = max(0.0, room.area - floor_minha)
            net_ceiling = max(0.0, room.area - ceiling_minha)
            net_wall = max(
                0.0,
                room.perimeter * room.height
                - door_minha
                - window_minha
                - wall_minha_extra,
            )
            net_skirting = max(
                0.0,
                room.perimeter - door_width_total - skirting_minha,
            )

            results.append(
                RoomQuantities(
                    room=room,
                    net_floor_m2=round(net_floor, 3),
                    net_ceiling_m2=round(net_ceiling, 3),
                    net_wall_m2=round(net_wall, 3),
                    net_skirting_m=round(net_skirting, 3),
                    door_count=len(doors),
                    window_count=len(windows),
                    door_minha_m2=round(door_minha, 3),
                    window_minha_m2=round(window_minha, 3),
                    door_width_total_m=round(door_width_total, 3),
                    floor_minha_m2=round(floor_minha, 3),
                    ceiling_minha_m2=round(ceiling_minha, 3),
                    wall_minha_extra_m2=round(wall_minha_extra, 3),
                    skirting_minha_m=round(skirting_minha, 3),
                )
            )
        logger.info("Quantities computed for %d rooms", len(results))
        return results
