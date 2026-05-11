"""Yapisal katman isimlerini ElementKind'a esleyen autodetect.

Mimari `autodetect.py` mahal/duvar/kapi katmanlarini tanir; bu modul
ise KOLON / PERDE / KIRIS / DOSEME gibi yapisal katmanlari tanir.
Cogu firma 'NA' (Naif Alan), 'SP' (Statik Proje), 'PRY' (proje) gibi
ekler kullaniyor; pattern'lar bunlara duyarli degil.

Faz 1 (skor sistemi):
* ``score_layer`` — ad regex + signal_hints ad alias + renk onyargisi + geometrik
  imza (alan/aspect ratio/dagilim). Cikti her ElementKind icin 0..~1.5 skor.
* ``detect_structural_layers`` — geri uyumlu API; ``signals`` ve ``signal_hints``
  verilirse skor sistemini, verilmezse eski regex-only davranisini kullanir.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, cast, get_args

from .elements import ElementKind
from .layer_signals import LayerSignals

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
    #: Faz 1: skor sistemi acikken her katman icin (en yuksek skorlu ilk 3 kind).
    #: Eski cagrilarda bos kalir. UI/diagnostics bunu "yakin alternatifler" olarak
    #: gosterebilir; skor < threshold ise zaten ``unmatched``.
    layer_scores: Dict[str, List[tuple]] = field(default_factory=dict)


# Faz 1: skor sisteminin kullandigi sabit agirliklari ortak yere topla; tests
# ve dokuman bu degerlerden okuyabilsin.
_NAME_REGEX_WEIGHT = 0.6
_NAME_ALIAS_WEIGHT = 0.5
_COLOR_HINT_WEIGHT = 0.3
_GEOM_SIGNATURE_WEIGHT = 0.4
_DUPLICATE_PENALTY = -0.8

#: Skor sisteminin "en yuksek" kind icin minimum kabul esigi.
_SCORE_THRESHOLD = 0.5


def _name_alias_score(
    name: str,
    signal_hints: Optional[Mapping[str, Any]],
) -> Dict[str, float]:
    """signal_hints['name_aliases'][kind] = [alias, alias, ...] ekstra skor."""
    out: Dict[str, float] = {}
    if not signal_hints:
        return out
    aliases = signal_hints.get("name_aliases") or {}
    if not isinstance(aliases, Mapping):
        return out
    upper = name.upper()
    for kind, alist in aliases.items():
        if not isinstance(alist, (list, tuple)):
            continue
        for alias in alist:
            a = str(alias).upper().strip()
            if a and a in upper:
                out[kind] = out.get(kind, 0.0) + _NAME_ALIAS_WEIGHT
                break  # ayni kind icin sadece bir alias yeter
    return out


def _color_hint_score(
    color: int,
    signal_hints: Optional[Mapping[str, Any]],
) -> Dict[str, float]:
    """signal_hints['color_hints'][kind] = [aci_code, ...] esleme."""
    out: Dict[str, float] = {}
    if not signal_hints:
        return out
    hints = signal_hints.get("color_hints") or {}
    if not isinstance(hints, Mapping):
        return out
    for kind, codes in hints.items():
        if not isinstance(codes, (list, tuple)):
            continue
        try:
            if int(color) in {int(c) for c in codes}:
                out[kind] = out.get(kind, 0.0) + _COLOR_HINT_WEIGHT
        except (TypeError, ValueError):
            continue
    return out


def _geometric_signature_score(signals: Optional[LayerSignals]) -> Dict[str, float]:
    """Alan / aspect ratio'dan turetilmis geometrik imza skoru.

    Kalibrasyon: Kumluca elemanlarinda gozlemlenen aralıklar referans.
    """
    out: Dict[str, float] = {}
    if signals is None or signals.closed_geom_count == 0:
        return out

    a_med = signals.area_median
    asp_med = signals.aspect_median
    asp_max = signals.aspect_max
    n = signals.closed_geom_count

    # Kolon imzasi: kucuk alan + kompakt + bir suru kopya (her katta tekrarli)
    if a_med < 5.0 and asp_med < 3.5 and n >= 5:
        out["column"] = out.get("column", 0.0) + _GEOM_SIGNATURE_WEIGHT

    # Perde imzasi: uzun-ince poligon (aspect >= 4)
    if asp_med >= 4.0 or asp_max >= 8.0:
        # alan da kucuk-orta olmali (cok genis perde olmaz)
        if a_med < 20.0:
            out["shear_wall"] = out.get("shear_wall", 0.0) + _GEOM_SIGNATURE_WEIGHT

    # Doseme imzasi: buyuk alan + kompakt
    if a_med >= 50.0 and asp_med < 3.0:
        out["slab"] = out.get("slab", 0.0) + _GEOM_SIGNATURE_WEIGHT

    # Temel/radye imzasi: cok buyuk + 1-3 polygon
    if a_med >= 100.0 and n <= 5 and asp_med < 3.0:
        out["foundation"] = out.get("foundation", 0.0) + _GEOM_SIGNATURE_WEIGHT * 0.75
        out["lean_concrete"] = out.get("lean_concrete", 0.0) + _GEOM_SIGNATURE_WEIGHT * 0.5

    # Parapet imzasi: orta alan + ad'a "PARAPET" yoksa imza tek basina yetmez
    if 1.0 <= a_med <= 30.0 and 1.5 <= asp_med <= 8.0 and n >= 3:
        out["parapet"] = out.get("parapet", 0.0) + _GEOM_SIGNATURE_WEIGHT * 0.5

    # Kiris imzasi: cok sayida acik polyline veya line, bu modul'de
    # closed-only baktigi icin yalnizca yan kanal (open_total_length / line_count)
    # ile etkin olur. ``score_layer`` icinde ek olarak hesaplanir.

    return out


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


def score_layer(
    layer_name: str,
    color: int = 7,
    signals: Optional[LayerSignals] = None,
    signal_hints: Optional[Mapping[str, Any]] = None,
) -> Dict[str, float]:
    """Tek katman icin ``ElementKind`` skor dagilimi.

    Sinyal kanallari:
      1. **Ad regex** (mevcut ``_RULES``, agirlik ``_NAME_REGEX_WEIGHT``).
      2. **Ad alias** (``signal_hints['name_aliases']``, ``_NAME_ALIAS_WEIGHT``).
      3. **Renk** (``signal_hints['color_hints']``, ``_COLOR_HINT_WEIGHT``).
      4. **Geometrik imza** (alan / aspect ratio, ``_GEOM_SIGNATURE_WEIGHT``).

    Cogalt katman regex'i (``_DUPLICATE_LAYER_RE``) tum skorlara
    ``_DUPLICATE_PENALTY`` ceza uygular. Bu sayede ``KOLON NA`` > ``IZ_KOLON_PRY``.

    Donus: ``{ElementKind: float}``. ``score_layer(...).get('column', 0.0)`` gibi
    kullanilir. Skor 0..~1.5 araliginda (toplam agirlik = 0.6+0.5+0.3+0.4 = 1.8).
    """
    scores: Dict[str, float] = {}

    # 1) Ad regex (mevcut _RULES, ilk eslesen kazanir)
    for rule in _RULES:
        if rule.pattern.search(layer_name):
            scores[rule.kind] = scores.get(rule.kind, 0.0) + _NAME_REGEX_WEIGHT
            break

    # 2) signal_hints name aliases
    for k, v in _name_alias_score(layer_name, signal_hints).items():
        scores[k] = scores.get(k, 0.0) + v

    # 3) signal_hints color hints
    for k, v in _color_hint_score(color, signal_hints).items():
        scores[k] = scores.get(k, 0.0) + v

    # 4) Geometrik imza
    for k, v in _geometric_signature_score(signals).items():
        scores[k] = scores.get(k, 0.0) + v

    # 5) Cogalt katman cezasi (TUM kindlere)
    if _is_duplicate_layer(layer_name):
        for k in list(scores.keys()):
            scores[k] = scores[k] + _DUPLICATE_PENALTY

    return scores


def _top_scores(scores: Mapping[str, float], n: int = 3) -> List[tuple]:
    """En yuksek n skoru (kind, score) sirali sirayla."""
    return sorted(scores.items(), key=lambda kv: -kv[1])[:n]


def detect_structural_layers(
    layers: Sequence[str],
    layer_inventory: Optional[Dict[str, Dict[str, int]]] = None,
    skip_empty: bool = True,
    skip_duplicate_layers: bool = True,
    *,
    layer_signals: Optional[Mapping[str, LayerSignals]] = None,
    layer_colors: Optional[Mapping[str, int]] = None,
    signal_hints: Optional[Mapping[str, Any]] = None,
) -> StructuralLayerReport:
    """Verilen katman listesinden yapisal eleman atamasi cikarir.

    ``skip_duplicate_layers=True``: PRY/IZ/MM gibi mimari kopya katmanlari
    yapisal kindlere atanmaz (cift sayimi engeller).

    Faz 1 (opsiyonel): ``layer_signals`` veya ``signal_hints`` verilirse
    ``score_layer`` ile skor sistemi devreye girer; renk + geometri imzalari
    ad regex'inin yaninda sinyal olarak kullanilir. Hicbiri verilmediyse
    eski regex-only davranisi aynen calisir (geri uyum).
    """
    layer_to_kind: Dict[str, ElementKind] = {}
    kind_to_layers: Dict[str, List[str]] = {}
    layer_scores: Dict[str, List[tuple]] = {}
    unmatched: List[str] = []
    skipped_duplicates: List[str] = []
    use_scoring = layer_signals is not None or signal_hints is not None

    for layer in layers:
        if skip_empty and layer_inventory is not None:
            counts = layer_inventory.get(layer, {})
            if not any(counts.values()):
                continue
        if skip_duplicate_layers and _is_duplicate_layer(layer):
            skipped_duplicates.append(layer)
            continue
        chosen: Optional[ElementKind] = None
        if use_scoring:
            sig = layer_signals.get(layer) if layer_signals else None
            col = (layer_colors or {}).get(layer, 7)
            scores = score_layer(
                layer_name=layer, color=col, signals=sig,
                signal_hints=signal_hints,
            )
            if scores:
                ordered = _top_scores(scores)
                layer_scores[layer] = ordered
                top_kind, top_score = ordered[0]
                if top_score >= _SCORE_THRESHOLD:
                    chosen = cast(ElementKind, top_kind)
        else:
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
        "Yapisal autodetect: %d katman atandi, %d eslesmedi, %d cift-kopya atlandi "
        "(skor modu: %s)",
        len(layer_to_kind),
        len(unmatched),
        len(skipped_duplicates),
        "acik" if use_scoring else "kapali",
    )
    return StructuralLayerReport(
        layer_to_kind=layer_to_kind,
        kind_to_layers={k: sorted(set(v)) for k, v in kind_to_layers.items()},
        unmatched=sorted(unmatched),
        layer_scores=layer_scores,
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
        layer_scores=dict(base.layer_scores),
    )
