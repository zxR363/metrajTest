"""DWG'deki plan basligi metinlerini analiz ederek her plana

  - kanonik kat etiketi ("TEMEL", "0,00", "3,00", ...)
  - kotu (m)
  - tipik kat plani ise multiplier (kac kat icin kullanildigi)
  - extra etiketler (tipik kat icin "9,00", "12,00" gibi ek etiketler)

atar.

Tipik plan basligi ornekleri:
  "BODRUM KAT PLANI"        -> TEMEL, multiplier=1
  "ZEMİN KAT PLANI"         -> 0,00, multiplier=1
  "1.KAT PLANI (+3.00)"     -> 3,00, multiplier=1
  "2.VE 3. KAT PLANI (+6.00)" -> 6,00, multiplier=2, extra=[9,00]
  "4. KAT PLANI (+9.00)"    -> 12,00, multiplier=1 (etiketteki +9.00 yanlis)
  "ÇATI KATI PLANI (+12.00)" -> 15,00 (cati uzerinde)

Faz 2: Bu modul, sabit Turkce regex'lerden dil-agnostik **PlanLabelLocale**'a
gecirildi. ``config/locale/plan_labels_tr.yaml`` (default) ve
``plan_labels_en.yaml`` dosyalarinda anahtar sozcukler yer alir; yeni firma
projesinde sadece anahtar listesini guncellemek yeterli.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

import yaml

from ..cad_io.dxf_reader import CadText
from .elements import FloorPlan

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Locale
# ---------------------------------------------------------------------------

_DEFAULT_LOCALE_DIR = Path(__file__).resolve().parents[2] / "config" / "locale"


@dataclass
class PlanLabelLocale:
    """Plan basligi anahtar sozcukleri (dil bazli)."""

    name: str = "tr"
    plan_keywords: List[str] = field(default_factory=lambda: ["PLAN", "PLANI", "PLANLARI"])
    floor_keyword: List[str] = field(default_factory=lambda: ["KAT", "KATI"])
    basement: List[str] = field(default_factory=lambda: ["BODRUM", "TEMEL"])
    ground: List[str] = field(default_factory=lambda: ["ZEMIN", "ZEMİN"])
    roof: List[str] = field(default_factory=lambda: ["CATI", "ÇATI"])
    multi_floor_separator: List[str] = field(default_factory=lambda: ["VE", ",", "&", "+"])
    elevation_marker: List[str] = field(default_factory=lambda: ["KOT", "KOTU"])

    @classmethod
    def from_dict(cls, data: dict, name: str = "custom") -> "PlanLabelLocale":
        def _lst(key: str, default: List[str]) -> List[str]:
            v = data.get(key)
            if not isinstance(v, list):
                return list(default)
            return [str(x) for x in v if str(x).strip()]
        base = cls()
        return cls(
            name=name,
            plan_keywords=_lst("plan_keywords", base.plan_keywords),
            floor_keyword=_lst("floor_keyword", base.floor_keyword),
            basement=_lst("basement", base.basement),
            ground=_lst("ground", base.ground),
            roof=_lst("roof", base.roof),
            multi_floor_separator=_lst("multi_floor_separator", base.multi_floor_separator),
            elevation_marker=_lst("elevation_marker", base.elevation_marker),
        )

    @classmethod
    def load(cls, source: str | Path) -> "PlanLabelLocale":
        """``source`` bir dosya yolu ya da locale adi (``tr``/``en``).

        ``tr`` veya ``en`` adi verilirse paket icindeki
        ``config/locale/plan_labels_<name>.yaml`` aranir.
        """
        path = Path(source)
        if not path.is_file() and not path.is_absolute():
            cand = _DEFAULT_LOCALE_DIR / f"plan_labels_{path.stem}.yaml"
            if cand.is_file():
                path = cand
        if not path.is_file():
            raise FileNotFoundError(f"plan_labels locale dosyasi bulunamadi: {source}")
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        return cls.from_dict(data, name=path.stem.replace("plan_labels_", ""))

    @classmethod
    def default(cls) -> "PlanLabelLocale":
        """Paket-icinde gomulu Turkce locale; dosya bulunmazsa kod default'u."""
        try:
            return cls.load("tr")
        except FileNotFoundError:
            return cls()


def _kw_alt_pattern(words: Iterable[str]) -> str:
    """Locale sozcuklerinden regex alternation cikar (kelime siniri ile)."""
    parts: List[str] = []
    for w in words:
        s = str(w).strip()
        if not s:
            continue
        # Ozel karakterler escape edilir.
        parts.append(re.escape(s))
    if not parts:
        # Hicbir sey eslestirme — bos pattern degil, asla match etmeyen pattern.
        return r"(?!x)x"
    return "|".join(parts)


def _compile_locale_patterns(locale: PlanLabelLocale):
    """Locale'den runtime regex'leri uret (cache yok cunku konfig nadiren degisir)."""
    floor_kw = _kw_alt_pattern(locale.floor_keyword)
    sep = _kw_alt_pattern(locale.multi_floor_separator)
    elev_mark = _kw_alt_pattern(locale.elevation_marker)

    return {
        "basement": re.compile(rf"\b(?:{_kw_alt_pattern(locale.basement)})\b", re.IGNORECASE),
        "ground": re.compile(rf"\b(?:{_kw_alt_pattern(locale.ground)})\b", re.IGNORECASE),
        "roof": re.compile(rf"\b(?:{_kw_alt_pattern(locale.roof)})\b", re.IGNORECASE),
        # "2.VE 3. KAT" / "2ND AND 3RD FLOOR" — suffix toleransli
        "multi_floor": re.compile(
            rf"(\d+)\s*(?:\.|ST|ND|RD|TH)?\s*(?:{sep})\s*(\d+)\s*(?:\.|ST|ND|RD|TH)?\s*(?:{floor_kw})",
            re.IGNORECASE,
        ),
        # "(+3.00 KOT)"
        "elev_paren": re.compile(
            rf"\(\s*([+\-]?\d+[.,]\d+)\s*(?:{elev_mark})?\s*\)",
            re.IGNORECASE,
        ),
        # "1. KAT" / "1ST FLOOR"
        "floor_num": re.compile(
            rf"(\d+)\s*(?:\.|ST|ND|RD|TH)\s*(?:{floor_kw})",
            re.IGNORECASE,
        ),
        "plan_keyword_set": frozenset(w.upper() for w in locale.plan_keywords),
        "floor_keyword_set": frozenset(w.upper() for w in locale.floor_keyword),
        "basement_set": frozenset(w.upper() for w in locale.basement),
        "ground_set": frozenset(w.upper() for w in locale.ground),
        "roof_set": frozenset(w.upper() for w in locale.roof),
    }


# Modul yuklenirken default TR locale ile pattern'leri hazirla; eski API'lerin
# uyumlu calismasi icin.
_DEFAULT_LOCALE = PlanLabelLocale.default()
_DEFAULT_PATTERNS = _compile_locale_patterns(_DEFAULT_LOCALE)


@dataclass
class PlanLabelInfo:
    canonical_label: str
    elevation_m: float
    multiplier: int = 1
    extra_labels: List[str] = None
    raw: str = ""

    def __post_init__(self):
        if self.extra_labels is None:
            self.extra_labels = []


def _kat_to_elevation(kat_num: int, storey_h: float = 3.0) -> float:
    """Kat numarasindan kotu cikar.

    1.kat = +3.00, 2.kat = +6.00, ...  Bodrum = -3.00, Zemin = 0.00.
    """
    return kat_num * storey_h


def _elev_to_label(elev: float) -> str:
    s = f"{elev:.2f}".replace(".", ",")
    if elev > 0:
        return f"+{s}"
    return s


_LONG_TEXT_THRESHOLD = 80


def _is_plausible_plan_title(upper: str, pats: dict) -> bool:
    """Token-bazli yapisal kural: ilk 8 tokende PLAN/FLOOR/LEVEL/KAT gecmesi yeterli.

    Eski "80 char ustu metin atlanir" heuristic'i yerine: uzun teknik aciklamalar
    da plan basligi olabilir ama yalniz **ilk 8 token icinde** plan/floor anahtar
    sozcugu varsa kabul edilir. Boylece 1000+ karakterlik teras detay metinleri
    ("zemin" gecse de) reddedilir.
    """
    if len(upper) > 400:
        return False  # 400+ char pratikte hicbir plan basligi degil (cok uzun aciklama)
    tokens = upper.split()
    head = tokens[:8]
    # Bazi tokenler nokta/virgul ile gelir; sadece token icinde substring kontrol:
    for tok in head:
        # token icindeki "PLANI", "PLANS", "PLAN" gibi ekleri yakalamak icin
        # plan_keyword_set elemanlarinin token icinde substring olup olmadigina bak.
        for kw in pats["plan_keyword_set"]:
            if kw in tok:
                return True
        for kw in pats["floor_keyword_set"]:
            if kw in tok:
                return True
    return False


_NUMERIC_ELEV_RE = re.compile(r"([+\-]?\d{1,2}[.,]\d{1,2})")


def parse_plan_title(
    text: str,
    storey_h: float = 3.0,
    locale: Optional[PlanLabelLocale] = None,
) -> Optional[PlanLabelInfo]:
    """Plan baslik metnini parse et.

    Algoritma:
      1. Multi-kat (``2 VE 3 KAT`` / ``1ST AND 2ND FLOOR``) — priority en yuksek.
      2. basement/ground/roof anahtar sozcukleri.
      3. ``N. KAT`` / ``Nth FLOOR``.
      4. ``(+3.00 KOT)`` gibi parantezli kot.
      5. **Fallback** (Faz 2): herhangi bir ``+/-XX.XX`` sayisal kot.

    ``locale``: locale tablosu (None ise modul yuklenirken cozulen TR default).
    """
    if not text:
        return None
    s = text.strip()
    raw = s
    pats = _DEFAULT_PATTERNS if locale is None else _compile_locale_patterns(locale)
    upper = s.upper()

    # Uzun metin (80+ char) icin token-bazli akil-yatkin plan basligi kontrolu:
    # ilk 8 token icinde PLAN/PLANI/FLOOR/KAT gecmiyorsa teknik aciklamadir,
    # reddet. Kisa metinler her zaman parse'a girer (eski davranis).
    if len(upper) > _LONG_TEXT_THRESHOLD and not _is_plausible_plan_title(upper, pats):
        return None

    # Tipik kat: "2 VE 3 KAT" / "2,3.KAT" / "1ST AND 2ND FLOOR"
    m_multi = pats["multi_floor"].search(upper)
    if m_multi:
        k1 = int(m_multi.group(1))
        k2 = int(m_multi.group(2))
        labels = []
        for k in range(k1, k2 + 1):
            labels.append(_elev_to_label(_kat_to_elevation(k, storey_h)))
        return PlanLabelInfo(
            canonical_label=labels[0],
            elevation_m=_kat_to_elevation(k1, storey_h),
            multiplier=len(labels),
            extra_labels=labels[1:],
            raw=raw,
        )

    if pats["basement"].search(upper):
        return PlanLabelInfo(canonical_label="TEMEL", elevation_m=-3.0, raw=raw)
    if pats["ground"].search(upper):
        return PlanLabelInfo(canonical_label="0,00", elevation_m=0.0, raw=raw)
    if pats["roof"].search(upper):
        # Cati plan: cogu zaman cati ust kotunu temsil eder; biz +15 varsayalim
        # ama metinden kotu da okuyalim
        m_kot = pats["elev_paren"].search(s)
        if m_kot:
            elev = float(m_kot.group(1).replace(",", "."))
            # Cati plan: + 12 kotu metnen ama gercek kati +15 olabilir
            # tedbirli: yazilan kotun bir kat ustu cikar
            return PlanLabelInfo(
                canonical_label=_elev_to_label(elev + storey_h),
                elevation_m=elev + storey_h,
                raw=raw,
            )
        return PlanLabelInfo(canonical_label="CATI", elevation_m=15.0, raw=raw)

    # Kat numarasi varsa ondan kot
    m_kat = pats["floor_num"].search(upper)
    if m_kat:
        k = int(m_kat.group(1))
        elev = _kat_to_elevation(k, storey_h)
        return PlanLabelInfo(
            canonical_label=_elev_to_label(elev),
            elevation_m=elev,
            raw=raw,
        )
    # Kotu okuma (parantez icindeki)
    m_kot = pats["elev_paren"].search(s)
    if m_kot:
        elev = float(m_kot.group(1).replace(",", "."))
        return PlanLabelInfo(
            canonical_label=_elev_to_label(elev),
            elevation_m=elev,
            raw=raw,
        )
    # Faz 2 sayisal-kot fallback: hicbir anahtar sozcuk yok ama plan/floor
    # token'i basta gecti ve sayisal kot var (orn. "PLAN +3.00").
    if _is_plausible_plan_title(upper, pats):
        m_num = _NUMERIC_ELEV_RE.search(s)
        if m_num:
            try:
                elev = float(m_num.group(1).replace(",", "."))
            except ValueError:
                return None
            return PlanLabelInfo(
                canonical_label=_elev_to_label(elev),
                elevation_m=elev,
                raw=raw,
            )
    return None


def _label_priority(
    info: "PlanLabelInfo",
    locale: Optional[PlanLabelLocale] = None,
) -> int:
    """Kanonik etiket bilgisinin guvenilirligi (yuksek > dusuk).

    Multi-kat (``2 VE 3 KAT``) en yuksek; sonra n.KAT/BODRUM/ZEMIN/CATI;
    en alt seviye saf kot bilgisi.

    Anchor kabulu icin metnin gercekten plan basligi olmasi sart:
    "PLAN" / "PLANI" kelimesi gecmeyen 'CATI' / 'BODRUM' geçen
    teknik notlar plan basligi degildir.
    """
    pats = _DEFAULT_PATTERNS if locale is None else _compile_locale_patterns(locale)
    raw_upper = info.raw.upper()
    tokens = set(raw_upper.split())
    has_plan = bool(tokens & pats["plan_keyword_set"]) or bool(
        tokens & pats["floor_keyword_set"]
    )
    if info.multiplier > 1 and has_plan:
        return 100
    if has_plan and (tokens & pats["basement_set"] or tokens & pats["ground_set"]):
        return 90
    if has_plan and tokens & pats["roof_set"]:
        return 80
    if has_plan and pats["floor_num"].search(raw_upper):
        return 70
    return 30  # saf kot ya da plan basligi olmayan metin


def detect_title_anchors(
    texts: List[CadText],
    storey_h: float = 3.0,
    locale: Optional[PlanLabelLocale] = None,
) -> List[Tuple[float, PlanLabelInfo]]:
    """DWG'deki plan basligi metinlerini bul.

    Sadece kanonik priority>=70 (BODRUM/ZEMIN/N.KAT/ÇATI/multi-kat) olanlar
    kabul edilir; saf kot etiketleri (priority=30) plan merkezine guven
    vermez.  Donus: x koordinata gore artana sirali (x, info) liste.
    """
    anchors: List[Tuple[float, PlanLabelInfo]] = []
    for t in texts:
        if not t.text:
            continue
        info = parse_plan_title(t.text, storey_h=storey_h, locale=locale)
        if info is None:
            continue
        if _label_priority(info, locale=locale) < 70:
            continue
        x, _ = t.insert
        anchors.append((x, info))
    anchors.sort(key=lambda a: a[0])
    return anchors


def detect_plan_multipliers(
    floor_plans: List[FloorPlan],
    texts: List[CadText],
    storey_h: float = 3.0,
    locale: Optional[PlanLabelLocale] = None,
) -> None:
    """Her plan icin DWG metinlerinden kanonik etiket+multiplier cikar.

    `floor_plans` listesinde inplace degisiklik yapar (label, multiplier,
    extra_labels alanlarini gunceller).

    Plan icine atama: text insert noktasi plan bbox icinde olmali (ya da
    en fazla 1 m disinda).  Birden cok aday varsa, "kanonik guc" sirasi:
       multi-kat > BODRUM/ZEMIN/ÇATI > n.KAT > saf kot.
    """
    # Her plan'in bbox'i icindeki plan basligi metinlerini topla
    candidates_per_plan: List[List[Tuple[int, str, PlanLabelInfo]]] = [
        [] for _ in floor_plans
    ]
    for t in texts:
        if not t.text:
            continue
        info = parse_plan_title(t.text, storey_h=storey_h, locale=locale)
        if info is None:
            continue
        priority = _label_priority(info, locale=locale)
        # Plan basligi olmayan metinleri (priority<70) atla
        if priority < 70:
            continue
        x, y = t.insert
        # Hangi plan'a aittir?  Sadece bbox icinde ya da cok yakin (1 m)
        for i, fp in enumerate(floor_plans):
            xmin, ymin, xmax, ymax = fp.bbox
            margin_x = 1.0
            margin_y = max((ymax - ymin) * 0.5, 5.0) + 5.0
            if (xmin - margin_x <= x <= xmax + margin_x and
                ymin - margin_y <= y <= ymax + margin_y):
                candidates_per_plan[i].append((priority, t.text.strip(), info))
                break

    for i, (fp, cands) in enumerate(zip(floor_plans, candidates_per_plan)):
        if not cands:
            logger.warning("Plan[%d] icin etiket metni bulunamadi (label=%s)",
                           i, fp.label)
            continue
        # En yuksek priority'li, varsa ek ipucu (multi-kat)
        cands.sort(key=lambda c: c[0], reverse=True)
        _, raw, info = cands[0]
        fp.label = info.canonical_label
        fp.elevation_m = info.elevation_m
        fp.multiplier = info.multiplier
        fp.extra_labels = info.extra_labels or []
        if info.multiplier > 1:
            logger.info(
                "Plan[%d] '%s' tipik kat plani: multiplier=%d (etiketler=%s)",
                i, raw, info.multiplier, [info.canonical_label] + (info.extra_labels or []),
            )
        else:
            logger.info("Plan[%d] '%s' -> etiket: %s (kotu=%s)",
                        i, raw[:40], info.canonical_label, info.elevation_m)
