"""Yapisal katman isimlerini ElementKind'a esleyen autodetect.

Mimari `autodetect.py` mahal/duvar/kapi katmanlarini tanir; bu modul
ise KOLON / PERDE / KIRIS / DOSEME gibi yapisal katmanlari tanir.
Cogu firma 'NA' (Naif Alan), 'SP' (Statik Proje), 'PRY' (proje) gibi
ekler kullaniyor; pattern'lar bunlara duyarli degil.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, cast, get_args

from .elements import ElementKind

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StructuralRule:
    kind: ElementKind
    pattern: re.Pattern
    description: str


# Kurallar oncelik sirasiyla. Spesifik (MINHA, PARAPET) once, generic (KOLON)
# sonra. PERDE'yi WALL'dan ayri tutuyoruz cunku perde betonarme tasiyici
# duvar — kalip iki yuz hesabi farkli.
_RULES: Sequence[StructuralRule] = (
    # --- Minhalar ---------------------------------------------------
    StructuralRule(
        kind="slab_opening",
        pattern=re.compile(
            r"(DOSEME[\s_-]?MINHA|DÖŞEME[\s_-]?MİNHA|SLAB[\s_-]?OPENING|"
            r"DOSEME[\s_-]?BOSLUK|DÖŞEME[\s_-]?BOŞLUK)",
            re.IGNORECASE,
        ),
        description="doseme bosluk/minha",
    ),
    # --- Parapetler -------------------------------------------------
    StructuralRule(
        kind="parapet",
        pattern=re.compile(
            r"(PARAPET|BARIYER[\s_-]?BETON)",
            re.IGNORECASE,
        ),
        description="parapet",
    ),
    # --- Asansor / baca / saft -------------------------------------
    StructuralRule(
        kind="elevator_shaft",
        pattern=re.compile(
            r"(ASANSOR[\s_-]?KULE|ASANSÖR[\s_-]?KULE|ASANSOR[\s_-]?BOSL|ELEVATOR[\s_-]?SHAFT)",
            re.IGNORECASE,
        ),
        description="asansor kule perdesi",
    ),
    StructuralRule(
        kind="chimney",
        pattern=re.compile(r"(\bBACA\b|CHIMNEY)", re.IGNORECASE),
        description="baca",
    ),
    # --- Temel & Grobeton -----------------------------------------
    StructuralRule(
        kind="foundation",
        pattern=re.compile(
            r"(\bTEMEL\s*(NA|PROJE|DUZ|DÜZ|RADYE)?$|"
            r"\bRADYE\b|FOUNDATION)",
            re.IGNORECASE,
        ),
        description="temel / radye",
    ),
    StructuralRule(
        kind="lean_concrete",
        pattern=re.compile(r"(GROBETON|GRO[\s_-]?BETON|LEAN[\s_-]?CONCRETE)", re.IGNORECASE),
        description="grobeton",
    ),
    StructuralRule(
        kind="protection",
        pattern=re.compile(r"(KORUMA[\s_-]?BETON|KORUMA[\s_-]?DUVAR|PROTECTION)", re.IGNORECASE),
        description="koruma betonu",
    ),
    StructuralRule(
        kind="roof_slab",
        pattern=re.compile(r"(\bCATI\b|\bÇATI\b|ROOF[\s_-]?SLAB|CATI[\s_-]?DOSEME)", re.IGNORECASE),
        description="cati dosemesi",
    ),
    # --- Yapisal kabuk -------------------------------------------
    StructuralRule(
        kind="column",
        pattern=re.compile(
            r"(\bKOLON\b|\bCOLUMN\b|BETONARME[\s_-]?KOLON|S[\s_-]?COLS)",
            re.IGNORECASE,
        ),
        description="kolon",
    ),
    StructuralRule(
        kind="shear_wall",
        pattern=re.compile(
            r"(\bPERDE\b|SHEAR[\s_-]?WALL|S[\s_-]?WALL|BETONARME[\s_-]?PERDE)",
            re.IGNORECASE,
        ),
        description="perde / shear wall",
    ),
    StructuralRule(
        kind="beam",
        pattern=re.compile(
            r"(\bKIRIS\b|\bKİRİŞ\b|\bBEAM\b|S[\s_-]?BEAMS|IZ[\s_-]?KIRIS)",
            re.IGNORECASE,
        ),
        description="kiris",
    ),
    StructuralRule(
        kind="slab",
        pattern=re.compile(
            r"(\bDOSEME\b|\bDÖŞEME\b|\bSLAB\b|FLOOR[\s_-]?SLAB|"
            r"BETONARME[\s_-]?DOSEME)",
            re.IGNORECASE,
        ),
        description="doseme",
    ),
    StructuralRule(
        kind="stair",
        pattern=re.compile(r"(MERDIVEN|MERDİVEN|STAIR)", re.IGNORECASE),
        description="merdiven",
    ),
)


@dataclass
class StructuralLayerReport:
    layer_to_kind: Dict[str, ElementKind]
    kind_to_layers: Dict[str, List[str]]
    unmatched: List[str]


_DUPLICATE_LAYER_RE = re.compile(
    r"("
    r"[-_](?:PRY|PROJE|ARC|RMA|GKN|PRHN|DOK|DON|DET|HS|MES)$|"
    r"\bIZ[_\s]|"               # IZ_ izdusum
    r"\bIZDUSUM[_\s]|"
    r"\bTARAMA\b|"              # KOLON TARAMA gibi tarama kopyasi
    r"\bMM[-_]|"                # MM-... mimari prefix
    r"\bA[-_]?TARAMA\b|"
    r"\bMIMARI[_\s]|"
    r"\bGORUNUS\b|\bGÖRÜNÜŞ\b|"
    r"\bIZI\b"                  # KIRIS IZI gibi
    r")",
    re.IGNORECASE,
)


def _is_duplicate_layer(name: str) -> bool:
    """Mimari/PRY/firma tarafindan çift cizilen yardimci katmanlari yakala.

    Asıl yapisal katmanlar genelde 'KOLON NA', 'KİRİŞ NA', 'PERDE NA',
    'DÖŞEME NA' gibi sade isimlerdir.  Sufiks/prefix ile bezenmis
    katmanlar (_PRY/_RMA/_GKN/TARAMA/IZ/MM-...) cogu zaman izdusum,
    tarama, donatı veya mimari kopyadir; bunlari yapisal kindlere
    atamamak cift sayimi onler.
    """
    return bool(_DUPLICATE_LAYER_RE.search(name))


def detect_structural_layers(
    layers: Sequence[str],
    layer_inventory: Optional[Dict[str, Dict[str, int]]] = None,
    skip_empty: bool = True,
    skip_duplicate_layers: bool = True,
) -> StructuralLayerReport:
    """Verilen katman listesinden yapisal eleman atamasi cikarir.

    `skip_duplicate_layers=True`: PRY/IZ/MM gibi mimari kopya katmanlari
    yapisal kindlere atanmaz (cift sayimi engeller).
    """
    layer_to_kind: Dict[str, ElementKind] = {}
    kind_to_layers: Dict[str, List[str]] = {}
    unmatched: List[str] = []
    skipped_duplicates: List[str] = []

    for layer in layers:
        if skip_empty and layer_inventory is not None:
            counts = layer_inventory.get(layer, {})
            if not any(counts.values()):
                continue
        if skip_duplicate_layers and _is_duplicate_layer(layer):
            skipped_duplicates.append(layer)
            continue
        chosen: Optional[ElementKind] = None
        for rule in _RULES:
            if rule.pattern.search(layer):
                chosen = rule.kind
                break
        if chosen:
            layer_to_kind[layer] = chosen
            kind_to_layers.setdefault(chosen, []).append(layer)
        else:
            unmatched.append(layer)

    logger.info(
        "Yapisal autodetect: %d katman atandi, %d eslesmedi, %d cift-kopya atlandi",
        len(layer_to_kind),
        len(unmatched),
        len(skipped_duplicates),
    )
    return StructuralLayerReport(
        layer_to_kind=layer_to_kind,
        kind_to_layers={k: sorted(set(v)) for k, v in kind_to_layers.items()},
        unmatched=sorted(unmatched),
    )


def _valid_element_kind_strings() -> frozenset[str]:
    return frozenset(get_args(ElementKind))


def _rebuild_kind_to_layers(layer_to_kind: Dict[str, ElementKind]) -> Dict[str, List[str]]:
    buckets: Dict[str, List[str]] = {}
    for lay, k in layer_to_kind.items():
        buckets.setdefault(k, []).append(lay)
    return {kk: sorted(set(vv)) for kk, vv in buckets.items()}


def apply_structural_layer_overrides(
    base: StructuralLayerReport,
    *,
    include_kind: Optional[Dict[str, str]] = None,
    exclude_layers: Optional[Sequence[str]] = None,
) -> StructuralLayerReport:
    """Autodetect sonrasinda kullanici katman tur atama / dahil etme / haric tutma."""
    valid = _valid_element_kind_strings()
    lt: Dict[str, ElementKind] = {
        lay: cast(ElementKind, k) for lay, k in base.layer_to_kind.items()
    }
    for lay in exclude_layers or []:
        lt.pop(lay, None)
    for lay, kind_raw in (include_kind or {}).items():
        kind_s = str(kind_raw).strip()
        if kind_s not in valid:
            logger.warning(
                "Yapisal katman '%s' icin gecersiz tur '%s' — atlandi.",
                lay,
                kind_raw,
            )
            continue
        lt[lay] = cast(ElementKind, kind_s)
    unmatched_out = sorted([u for u in base.unmatched if u not in lt])
    return StructuralLayerReport(
        layer_to_kind=lt,
        kind_to_layers=_rebuild_kind_to_layers(lt),
        unmatched=unmatched_out,
    )
