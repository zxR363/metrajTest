"""Heuristic / data-driven tip assignment.

Given a list of detected rooms, assign default ``floor_tip``, ``wall_tip``,
``ceiling_tip`` and ``skirting_tip`` codes based on:

1. Mahal adi (room name) regex patterns -- e.g. WC -> wet-area kategori
2. A learnt cache from previous projects (mahal_name -> tip_set), saved to
   a small YAML file.
3. The ``TipDefinitions`` available in the active project: kural sadece
   "wet" / "circulation" / "office" / "service" / "assembly" gibi soyut
   katergori uretir, gercek kod (ornegin ``DS4`` veya ``Z2``) konfigde
   tanimli olan ilk uygun tipten secilir.

Bu sayede TipAssigner referans projenin kod kumesinden bagimsizdir.

UI override eder; bu modul yalnizca ilk atamayi yapar.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Mapping, Optional, Sequence

import yaml

from ..mapping import TipDefinitions
from .detector import Room

logger = logging.getLogger(__name__)


# Soyut profil: "wet" = islak hacim, "circulation" = sirkulasyon, vs.
RoomProfile = str

# Mahal adi -> profil eslesmesi.  Her firma kendi tip kodlarini
# kullanabildigi icin burada sadece soyut profile karar veriyoruz; gercek
# kod TipDefinitions'tan profile uygun ilk girisi cekerek bulunur.
DEFAULT_PROFILE_RULES: list[tuple[re.Pattern, RoomProfile]] = [
    (re.compile(r"WC|TUVALET|LAVABO|BANYO|DUS", re.IGNORECASE), "wet"),
    (re.compile(r"KORIDOR|HOL|GALERI|FUAYE|GIRIS", re.IGNORECASE), "circulation"),
    (re.compile(r"AMFI|SALON|KONFERANS|DURUSMA|TIYATRO|SINEMA", re.IGNORECASE), "assembly"),
    (re.compile(r"MERDIVEN|MERDIVENH", re.IGNORECASE), "stair"),
    (re.compile(r"DEPO|ARSIV|DOSYA|MUTFAK|YEMEKHANE", re.IGNORECASE), "service"),
    (re.compile(r"PANO|TRAFO|MEKANIK|TESISAT|SAFT", re.IGNORECASE), "technical"),
    (re.compile(r"OFIS|BURO|CALISMA|MAKAM|TOPLANTI|ODA", re.IGNORECASE), "office"),
]

# Profil -> tanim ile eslesen anahtar kelime kumesi (tip kodlarinin
# tanimlarinda aranir).  Boylece firma kendi kodlamasini kullansa bile
# (D1/W1/T1 ya da DS4/DV7/TV2) uygun esleme bulunur.
PROFILE_KEYWORDS = {
    "wet": ["islak", "wet", "seramik", "porselen", "su yali", "banyo"],
    "circulation": ["koridor", "hol", "circulation", "porselen 60",
                    "porselen", "general"],
    "assembly": ["hali", "amfi", "salon", "akustik", "carpet"],
    "stair": ["mermer basamak", "merdiven", "mermer"],
    "service": ["porselen", "general", "depo", "service"],
    "technical": ["epoksi", "korund", "yuzey sertlestirici", "technical"],
    "office": ["laminat", "ofis", "buro", "office", "hali", "carpet"],
    "default": ["porselen 60", "porselen", "general", "saten", "boya"],
}


@dataclass
class TipDefaults:
    floor_tip: Optional[str] = None
    wall_tip: Optional[str] = None
    ceiling_tip: Optional[str] = None
    skirting_tip: Optional[str] = None


class TipAssigner:
    """Assign tip codes to a sequence of rooms using rules + optional cache.

    Tip kod kumesinden bagimsiz: ``TipDefinitions`` icinde hangi kategoriler
    icin hangi kodlar varsa onlardan secer.  Konfig bostsa hicbir tip
    atamaz; bu durumda kullanici manuel olarak tip atamak zorundadir.
    """

    def __init__(
        self,
        tip_definitions: Optional[TipDefinitions] = None,
        rules: Sequence[tuple[re.Pattern, RoomProfile]] = DEFAULT_PROFILE_RULES,
        cache_path: Optional[Path] = None,
    ) -> None:
        self.tip_definitions = tip_definitions
        self.rules = list(rules)
        self.cache_path = cache_path
        self.cache: Dict[str, TipDefaults] = {}
        if cache_path and cache_path.exists():
            try:
                raw = yaml.safe_load(cache_path.read_text(encoding="utf-8")) or {}
                for name, defaults in raw.items():
                    self.cache[name.upper()] = TipDefaults(**defaults)
            except Exception:
                logger.exception("Tip cache yuklenemedi: %s", cache_path)

    def assign(self, rooms: Sequence[Room]) -> None:
        for room in rooms:
            defaults = self._lookup(room.name)
            if defaults.floor_tip and not room.floor_tip:
                room.floor_tip = defaults.floor_tip
            if defaults.wall_tip and not room.wall_tip:
                room.wall_tip = defaults.wall_tip
            if defaults.ceiling_tip and not room.ceiling_tip:
                room.ceiling_tip = defaults.ceiling_tip
            if defaults.skirting_tip and not room.skirting_tip:
                room.skirting_tip = defaults.skirting_tip

    def _lookup(self, name: str) -> TipDefaults:
        if not name:
            return self._defaults_for_profile("default")
        cached = self.cache.get(name.upper())
        if cached:
            return cached
        for pattern, profile in self.rules:
            if pattern.search(name):
                return self._defaults_for_profile(profile)
        return self._defaults_for_profile("default")

    def _defaults_for_profile(self, profile: RoomProfile) -> TipDefaults:
        if not self.tip_definitions or not self.tip_definitions.tipler:
            return TipDefaults()
        keywords = PROFILE_KEYWORDS.get(profile, PROFILE_KEYWORDS["default"])
        defaults = TipDefaults()
        for kategori_field, kategori in (
            ("floor_tip", "DOSEME"),
            ("wall_tip", "DUVAR"),
            ("ceiling_tip", "TAVAN"),
            ("skirting_tip", "SUPURGELIK"),
        ):
            tip = self._best_tip_for(kategori, keywords)
            if tip:
                setattr(defaults, kategori_field, tip)
        return defaults

    def _best_tip_for(self, kategori: str, keywords: Sequence[str]) -> Optional[str]:
        if not self.tip_definitions:
            return None
        candidates = [t for t in self.tip_definitions.tipler.values()
                      if t.kategori == kategori]
        if not candidates:
            return None
        # Score by keyword match in tanim
        scored: list[tuple[int, str]] = []
        for tip in candidates:
            tanim = (tip.tanim or "").lower()
            score = sum(1 for kw in keywords if kw in tanim)
            scored.append((score, tip.code))
        scored.sort(key=lambda kv: (-kv[0], kv[1]))
        return scored[0][1] if scored else None

    def remember(self, name: str, defaults: TipDefaults) -> None:
        self.cache[name.upper()] = defaults

    def save(self) -> None:
        if not self.cache_path:
            return
        out = {name: {k: v for k, v in d.__dict__.items() if v is not None}
               for name, d in self.cache.items()}
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(
            yaml.safe_dump(out, allow_unicode=True, sort_keys=True), encoding="utf-8")
