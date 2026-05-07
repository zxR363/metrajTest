"""Compare two metraj outputs (revisions) and report differences.

Inputs are pairs of (RoomQuantities, PozTotals).  The comparator emits
plain-Python dictionaries describing added/removed rooms, area deltas above a
threshold, and poz tutar deltas.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from ..pozlar import IcmalRow, PozTotals
from ..quantities import RoomQuantities

logger = logging.getLogger(__name__)


@dataclass
class RoomDelta:
    code: str
    name: str
    area_old: float
    area_new: float
    perimeter_old: float
    perimeter_new: float

    @property
    def area_diff(self) -> float:
        return self.area_new - self.area_old

    @property
    def area_pct(self) -> float:
        if not self.area_old:
            return 100.0 if self.area_new else 0.0
        return (self.area_new - self.area_old) / self.area_old * 100.0


@dataclass
class PozDelta:
    poz_no: str
    kategori: str
    tanim: str
    miktar_old: float
    miktar_new: float
    tutar_old: float
    tutar_new: float

    @property
    def tutar_diff(self) -> float:
        return self.tutar_new - self.tutar_old


@dataclass
class RevisionReport:
    rooms_added: List[RoomQuantities] = field(default_factory=list)
    rooms_removed: List[RoomQuantities] = field(default_factory=list)
    rooms_changed: List[RoomDelta] = field(default_factory=list)
    pozlar_changed: List[PozDelta] = field(default_factory=list)
    grand_total_old: float = 0.0
    grand_total_new: float = 0.0

    @property
    def grand_total_diff(self) -> float:
        return self.grand_total_new - self.grand_total_old


class RevisionComparator:
    def __init__(self, area_threshold_pct: float = 1.0,
                 tutar_threshold: float = 1.0) -> None:
        self.area_threshold_pct = area_threshold_pct
        self.tutar_threshold = tutar_threshold

    def compare(
        self,
        old_quantities: Sequence[RoomQuantities],
        new_quantities: Sequence[RoomQuantities],
        old_icmal: PozTotals,
        new_icmal: PozTotals,
    ) -> RevisionReport:
        old_by_code: Dict[str, RoomQuantities] = {q.room.code: q for q in old_quantities}
        new_by_code: Dict[str, RoomQuantities] = {q.room.code: q for q in new_quantities}
        report = RevisionReport()

        for code, q in new_by_code.items():
            if code not in old_by_code:
                report.rooms_added.append(q)
        for code, q in old_by_code.items():
            if code not in new_by_code:
                report.rooms_removed.append(q)
        for code in set(new_by_code) & set(old_by_code):
            old_q = old_by_code[code]
            new_q = new_by_code[code]
            delta = RoomDelta(
                code=code,
                name=new_q.room.name,
                area_old=old_q.room.area,
                area_new=new_q.room.area,
                perimeter_old=old_q.room.perimeter,
                perimeter_new=new_q.room.perimeter,
            )
            if abs(delta.area_pct) >= self.area_threshold_pct:
                report.rooms_changed.append(delta)

        old_pozlar = {r.poz_no: r for r in old_icmal.rows}
        new_pozlar = {r.poz_no: r for r in new_icmal.rows}
        for poz_no in set(old_pozlar) | set(new_pozlar):
            old_r = old_pozlar.get(poz_no)
            new_r = new_pozlar.get(poz_no)
            if old_r and new_r:
                delta = PozDelta(
                    poz_no=poz_no,
                    kategori=new_r.kategori,
                    tanim=new_r.tanim,
                    miktar_old=old_r.miktar,
                    miktar_new=new_r.miktar,
                    tutar_old=old_r.tutar,
                    tutar_new=new_r.tutar,
                )
            elif new_r:
                delta = PozDelta(poz_no=poz_no, kategori=new_r.kategori,
                                 tanim=new_r.tanim, miktar_old=0.0,
                                 miktar_new=new_r.miktar, tutar_old=0.0,
                                 tutar_new=new_r.tutar)
            else:
                delta = PozDelta(poz_no=poz_no, kategori=old_r.kategori,
                                 tanim=old_r.tanim, miktar_old=old_r.miktar,
                                 miktar_new=0.0, tutar_old=old_r.tutar,
                                 tutar_new=0.0)
            if abs(delta.tutar_diff) >= self.tutar_threshold:
                report.pozlar_changed.append(delta)

        report.grand_total_old = old_icmal.grand_total
        report.grand_total_new = new_icmal.grand_total
        report.rooms_changed.sort(key=lambda d: abs(d.area_diff), reverse=True)
        report.pozlar_changed.sort(key=lambda d: abs(d.tutar_diff), reverse=True)
        return report
