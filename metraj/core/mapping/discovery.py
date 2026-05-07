"""Discover tipler ve pozlar that the active project uses but the YAML
configuration does not define yet.

Used by Faz 0 to produce a "config gap" report so a new project can be
configured incrementally instead of crashing on the first missing tip.
"""
from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Set

from ..rooms import Room
from .config import PozLibrary, TipDefinitions

logger = logging.getLogger(__name__)


@dataclass
class ConfigDiscoveryReport:
    """Tip + poz eksiklikleri."""

    used_tipler: Counter
    missing_tipler: Set[str]
    missing_pozlar: Set[str]
    suggested_kategori: Dict[str, str]  # tip code -> guessed kategori (DOSEME/...)

    def has_gaps(self) -> bool:
        return bool(self.missing_tipler) or bool(self.missing_pozlar)

    def summary(self) -> str:
        lines = []
        if self.missing_tipler:
            lines.append(
                f"Tanimsiz tip kodlari ({len(self.missing_tipler)}): "
                f"{', '.join(sorted(self.missing_tipler))}"
            )
        if self.missing_pozlar:
            lines.append(
                f"Tanimsiz poz numaralari ({len(self.missing_pozlar)}): "
                f"{', '.join(sorted(self.missing_pozlar))}"
            )
        if not lines:
            lines.append("Konfigde eksik bir sey yok.")
        return "\n".join(lines)


def discover_config_gaps(
    rooms: Sequence[Room],
    tip_definitions: TipDefinitions,
    poz_library: PozLibrary,
) -> ConfigDiscoveryReport:
    counter = Counter()
    suggested: Dict[str, str] = {}
    for room in rooms:
        for code, kategori in (
            (room.floor_tip, "DOSEME"),
            (room.wall_tip, "DUVAR"),
            (room.ceiling_tip, "TAVAN"),
            (room.skirting_tip, "SUPURGELIK"),
        ):
            if code:
                counter[code] += 1
                suggested.setdefault(code, kategori)

    missing_tipler = {code for code in counter if not tip_definitions.get(code)}
    missing_pozlar: Set[str] = set()
    for code in counter:
        tip = tip_definitions.get(code)
        if not tip:
            continue
        for assignment in tip.pozlar:
            if not poz_library.get(assignment.poz_no):
                missing_pozlar.add(assignment.poz_no)
    return ConfigDiscoveryReport(
        used_tipler=counter,
        missing_tipler=missing_tipler,
        missing_pozlar=missing_pozlar,
        suggested_kategori=suggested,
    )


def synthesize_missing_tipler(
    report: ConfigDiscoveryReport,
    tip_definitions: TipDefinitions,
    poz_library: PozLibrary,
) -> Dict[str, "_TipBlueprint"]:
    """Eksik tipler icin sablon olustur (jenerik bir poz reçetesi atar).

    Cikti dogrudan YAML olarak yazilabilen sade dataclass'tir; kullanici
    duzenleyip kalici hale getirir.
    """
    from .config import TipDefinition, TipPozAssignment  # local import: avoid cycles

    blueprints: Dict[str, "_TipBlueprint"] = {}
    fallback_pozlar = {
        "DOSEME": ("15.385.1028", "15.250.1011", "15.250.1111"),
        "DUVAR": ("15.275.1116", "15.280.1011", "15.540.1531"),
        "TAVAN": ("15.275.1113", "15.540.1523"),
        "SUPURGELIK": ("15.405.1701",),
    }
    for code in report.missing_tipler:
        kategori = report.suggested_kategori.get(code, "DOSEME")
        pozlar = fallback_pozlar.get(kategori, ())
        blueprints[code] = _TipBlueprint(
            code=code,
            kategori=kategori,
            pozlar=[(p, 1.0) for p in pozlar if poz_library.get(p)],
            tanim=f"Otomatik uretildi ({kategori})",
        )
    return blueprints


@dataclass
class _TipBlueprint:
    code: str
    kategori: str
    pozlar: List[tuple]
    tanim: str = ""

    def to_yaml_dict(self) -> dict:
        return {
            "kategori": self.kategori,
            "tanim": self.tanim,
            "pozlar": [{"poz_no": p, "pay": pay} for p, pay in self.pozlar],
        }
