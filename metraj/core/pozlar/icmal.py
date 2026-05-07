"""Aggregate per-room quantities into category/poz totals (Icmal sheet)."""
from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from ..mapping import PozLibrary, TipDefinitions
from ..openings import Opening
from ..quantities import RoomQuantities

logger = logging.getLogger(__name__)


@dataclass
class IcmalRow:
    poz_no: str
    kategori: str
    tanim: str
    birim: str
    miktar: float
    birim_fiyat: float

    @property
    def tutar(self) -> float:
        return self.miktar * self.birim_fiyat


@dataclass
class PozTotals:
    rows: List[IcmalRow] = field(default_factory=list)
    by_kategori: Dict[str, float] = field(default_factory=lambda: defaultdict(float))

    @property
    def grand_total(self) -> float:
        return sum(r.tutar for r in self.rows)


class IcmalAggregator:
    """Map per-room quantities through tip definitions to the Icmal sheet.

    The tip table provides the recipe: a single floor type ``DS3`` translates
    to multiple pozlar (terrazo + tesviye + sap) each receiving (potentially
    fractional) m2 from the same net area.
    """

    def __init__(self, tip_definitions: TipDefinitions, poz_library: PozLibrary) -> None:
        self.tipler = tip_definitions
        self.pozlar = poz_library

    def aggregate(
        self,
        quantities: Sequence[RoomQuantities],
        openings: Optional[Sequence[Opening]] = None,
        wall_band_areas: Optional[Dict[str, float]] = None,
    ) -> PozTotals:
        per_poz: Dict[str, float] = defaultdict(float)

        for q in quantities:
            for tip_code, base_qty in self._tip_base_quantities(q).items():
                tip = self.tipler.get(tip_code) if tip_code else None
                if not tip:
                    continue
                for assignment in tip.pozlar:
                    per_poz[assignment.poz_no] += base_qty * assignment.pay

        # Doors & windows -> DOGRAMA pozlari (m2)
        if openings:
            door_area = sum(o.area for o in openings if o.kind == "door")
            window_area = sum(o.area for o in openings if o.kind == "window")
            if door_area:
                per_poz["15.430.1104"] = per_poz.get("15.430.1104", 0.0) + door_area
            if window_area:
                per_poz["15.430.1201"] = per_poz.get("15.430.1201", 0.0) + window_area

        # Wall thickness bands (KABUK / DUVAR-IMALAT) -> here we only emit
        # length totals as informational rows; firma poz haritasiyla
        # genisletilebilir.
        # (Bos birakildi: real projede tugla/gazbeton tip pozlarina bagli.)

        totals = PozTotals()
        for poz_no, miktar in per_poz.items():
            entry = self.pozlar.get(poz_no)
            if not entry:
                logger.warning("Poz '%s' not found in poz library; skipping", poz_no)
                continue
            row = IcmalRow(
                poz_no=poz_no,
                kategori=entry.kategori,
                tanim=entry.tanim,
                birim=entry.birim,
                miktar=round(miktar, 3),
                birim_fiyat=entry.birim_fiyat,
            )
            totals.rows.append(row)
            totals.by_kategori[entry.kategori] += row.tutar
        totals.rows.sort(key=lambda r: (r.kategori, r.poz_no))
        return totals

    def _tip_base_quantities(self, q: RoomQuantities) -> Dict[str, float]:
        """Return base quantity (m2 or m) per tip kategori for one room."""
        base: Dict[str, float] = {}
        if q.room.floor_tip:
            base[q.room.floor_tip] = q.net_floor_m2
        if q.room.ceiling_tip:
            base[q.room.ceiling_tip] = q.net_ceiling_m2
        if q.room.wall_tip:
            base[q.room.wall_tip] = q.net_wall_m2
        if q.room.skirting_tip:
            base[q.room.skirting_tip] = q.net_skirting_m
        return base
