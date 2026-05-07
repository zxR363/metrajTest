"""DXF katman isimlerinden semantik rolleri otomatik tespit etme.

Her firmanin katman isimleme standardi farkli oldugu icin sabit liste
yetersiz kalir. Bu modul DXF'teki katman isimlerini desen tabanli kurallara
gore puanlayip ``LayerMap`` onerisi uretir.  Sonuc YAML olarak yazilabilir
ve kullanici tarafindan dogrulanip duzenlendikten sonra ana konfige
tasinabilir.

Kurallarin onceligi tepedeki -> en spesifik (door/window) -> sondaki ->
en jenerik (wall).  Bir katman birden cok kurali eslersse en yuksek
oncelikli kazanir.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from ..cad_io.dxf_reader import RawCadModel, inventory_layers
from .config import LayerMap, LayerRole

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DetectionRule:
    role: str
    pattern: re.Pattern
    description: str


# Kurallar oncelik sirasina gore:  spesifik -> jenerik.
# Hem Turkce (KAPI/PENCERE/DUVAR/MAHAL) hem AIA (A-DOOR/A-GLAZ/A-WALL)
# kalibrasyonsuz calisir.
_RULES: Sequence[DetectionRule] = (
    # Mahal etiketleri: en spesifik kalip (ODA LEJANTI / ODA NO / OD-NO / ROOM-NO)
    # tekstrik karistirma riskini azaltmak icin ROOM/MAHAL'dan once konuldu.
    DetectionRule(
        role="room_label",
        pattern=re.compile(
            r"(\bODA[\s_-]?(LEJ|LEJANT|NO|TAG|ETIKET|ISIM|ADI|KOD)"
            r"|MAHAL[\s_-]?(NO|LEJ|LEJANT|ETIKET|ISIM|ADI|KOD)?"
            r"|\bROOM[\s_-]?(NO|TAG|NAME|ID|LABEL)?"
            r"|AREA[-_\s]?IDEN|A[-_]?ROOM|OD[-_]?NO|ANNO[-_]?AREA|ETIKET[-_\s]?MAHAL"
            r"|MAHAL[-_\s]?LEJANT|ROOM[-_\s]?LEGEND|MAHAL[-_\s]?LISTE)",
            re.IGNORECASE,
        ),
        description="mahal etiketi/numarasi",
    ),
    DetectionRule(
        role="room_boundary",
        pattern=re.compile(
            r"(MAHAL[-_]?SINIR|A[-_]?AREA(?![-_]IDEN)|AREA[-_]?BDRY|ROOM[-_]?BDRY"
            r"|ODA[-_\s]?SINIR|MAHAL[-_\s]?CIZGI)",
            re.IGNORECASE,
        ),
        description="mahal sinir polyline/hatch",
    ),
    DetectionRule(
        role="door",
        pattern=re.compile(r"(KAPI|DOOR|A[-_]?DOOR)", re.IGNORECASE),
        description="kapi blogu",
    ),
    DetectionRule(
        role="window",
        pattern=re.compile(r"(PENCERE|WINDOW|A[-_]?GLAZ|A[-_]?WIN)", re.IGNORECASE),
        description="pencere blogu",
    ),
    DetectionRule(
        role="opening_internal",
        pattern=re.compile(r"(IC[-_]?ACIKLIK|OPNG|INT[-_]?OPENING)", re.IGNORECASE),
        description="ic aciklik/gecis",
    ),
    DetectionRule(
        role="column",
        pattern=re.compile(r"(KOLON|A[-_]?COLS|S[-_]?COLS)", re.IGNORECASE),
        description="kolon",
    ),
    DetectionRule(
        role="stair",
        pattern=re.compile(r"(MERDIVEN|MERDİVEN|STAIR|FLOR[-_]?STRS)", re.IGNORECASE),
        description="merdiven",
    ),
    DetectionRule(
        role="shaft",
        pattern=re.compile(r"(\bSAFT\b|SHAFT|RISR|\bBACA\b|ASANSOR[-_]?BOSL)", re.IGNORECASE),
        description="saft / baca / asansor boslugu",
    ),
    DetectionRule(
        role="balcony",
        pattern=re.compile(r"(\bBALKON\b|BALCONY|TERAS|TERRACE)", re.IGNORECASE),
        description="balkon / teras",
    ),
    DetectionRule(
        role="hatch_floor",
        pattern=re.compile(
            r"(DOSEME[-_]?HATCH|FLOR[-_]?HATC|FLOOR[-_]?HATCH|DOSEME[-_]?DESEN"
            r"|\bTARAMA\b|HATCH[-_]?FLOOR|ZEMIN[-_]?KAPLAMA)",
            re.IGNORECASE,
        ),
        description="doseme kaplama hatch'i",
    ),
    DetectionRule(
        role="furniture",
        pattern=re.compile(
            r"(MOBILYA|\bTEFRIS\b|\bTEFRİŞ\b|FURN|EQPM|\bEQP\b)",
            re.IGNORECASE,
        ),
        description="mobilya/ekipman/tefris",
    ),
    DetectionRule(
        role="grid",
        pattern=re.compile(r"(\bGRID\b|\bAKS\b)", re.IGNORECASE),
        description="aks/grid",
    ),
    DetectionRule(
        role="text_height",
        pattern=re.compile(
            r"(ANNO[-_]?DIMS|\bOLCU\b|\bDIMS?\b|IC[-_\s]?OLCU|DIS[-_\s]?OLCU"
            r"|İÇ[-_\s]?ÖLÇÜ|DIŞ[-_\s]?ÖLÇÜ|VAZIYET[-_\s]?OLCU|VAZİYET[-_\s]?ÖLÇÜ)",
            re.IGNORECASE,
        ),
        description="olculendirme",
    ),
    DetectionRule(
        role="wall_partition",
        pattern=re.compile(r"(BOLME|WALL[-_]?PART|WALL[-_]?PRHT)", re.IGNORECASE),
        description="bolme duvari",
    ),
    DetectionRule(
        role="wall",
        pattern=re.compile(
            r"(\bDUVAR\b|\bWALL\b|A[-_]?WALL|MIM[-_]?DUVAR|S[-_]?WALL|\bPERDE\b)",
            re.IGNORECASE,
        ),
        description="ana duvar / perde duvar",
    ),
)


@dataclass
class AutodetectReport:
    proposed_map: Dict[str, str]
    role_to_layers: Dict[str, List[str]]
    unmatched: List[str]
    candidates_per_layer: Dict[str, List[Tuple[str, str]]]  # layer -> [(role, desc)]


def autodetect_layer_map(
    model: RawCadModel,
    skip_empty: bool = True,
    base_map: Optional[LayerMap] = None,
) -> AutodetectReport:
    """Analyze layers in *model* and propose a role-per-layer mapping.

    Parameters
    ----------
    skip_empty:
        Eger True ise icinde hicbir entity bulunmayan katmanlar atlanir.
    base_map:
        Onceden tanimli bir LayerMap; bu katmanlar dokunulmaz, yalniz
        eslenmemis olanlar icin oneri uretilir.
    """
    inventory = inventory_layers(model)
    proposed: Dict[str, str] = {}
    role_to_layers: Dict[str, List[str]] = {}
    unmatched: List[str] = []
    candidates: Dict[str, List[Tuple[str, str]]] = {}

    for layer in model.layers:
        counts = inventory.get(layer, {})
        if skip_empty and not any(counts.values()):
            continue
        if base_map and base_map.role_of(layer):
            role = base_map.role_of(layer)
            assert role is not None
            proposed[layer] = role
            role_to_layers.setdefault(role, []).append(layer)
            continue
        match: Optional[Tuple[str, str]] = None
        all_matches: List[Tuple[str, str]] = []
        for rule in _RULES:
            if rule.pattern.search(layer):
                all_matches.append((rule.role, rule.description))
                if match is None:
                    match = (rule.role, rule.description)
        candidates[layer] = all_matches
        if match:
            proposed[layer] = match[0]
            role_to_layers.setdefault(match[0], []).append(layer)
        else:
            unmatched.append(layer)
    logger.info(
        "Autodetect: %d katman eslesti, %d eslesmedi (%d kural denendi).",
        len(proposed),
        len(unmatched),
        len(_RULES),
    )
    return AutodetectReport(
        proposed_map=proposed,
        role_to_layers={r: sorted(set(ls)) for r, ls in role_to_layers.items()},
        unmatched=unmatched,
        candidates_per_layer=candidates,
    )


def merge_into_layer_map(report: AutodetectReport, base_map: Optional[LayerMap] = None) -> LayerMap:
    """Combine autodetect results with an existing LayerMap (autodetect kazanir
    sadece eslesmemis katmanlar icin)."""
    roles: Dict[str, LayerRole] = {}
    if base_map:
        for role, entry in base_map.roles.items():
            roles[role] = LayerRole(role=role, layers=list(entry.layers), notes=entry.notes)
    for role, layers in report.role_to_layers.items():
        existing = roles.get(role)
        if existing:
            merged = sorted({*existing.layers, *layers})
            roles[role] = LayerRole(role=role, layers=merged, notes=existing.notes)
        else:
            roles[role] = LayerRole(role=role, layers=sorted(layers))
    layer_map = LayerMap(roles=roles)
    layer_map._layer_to_role = {  # type: ignore[attr-defined]
        l.upper(): r for r, entry in roles.items() for l in entry.layers
    }
    return layer_map
