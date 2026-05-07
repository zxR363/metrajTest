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
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

from ..cad_io.dxf_reader import CadText
from .elements import FloorPlan

logger = logging.getLogger(__name__)


_MULTI_KAT_RE = re.compile(
    r"(\d+)\s*\.?\s*(?:VE|,|&|\+)\s*(\d+)\s*\.?\s*KAT",
    re.IGNORECASE,
)
_KOT_RE = re.compile(
    r"\(\s*([+\-]?\d+[.,]\d+)\s*KOT[U]?\s*\)",
    re.IGNORECASE,
)
_KAT_NUM_RE = re.compile(r"(\d+)\s*\.\s*KAT", re.IGNORECASE)


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


_BODRUM_RE = re.compile(r"\bBODRUM\b|\bTEMEL\b", re.IGNORECASE)
_ZEMIN_RE = re.compile(r"\bZEMI[N|İ]N?\b|\bZEM[İI]N\b", re.IGNORECASE)
_CATI_RE = re.compile(r"\b[ÇC]ATI\b", re.IGNORECASE)


def parse_plan_title(text: str, storey_h: float = 3.0) -> Optional[PlanLabelInfo]:
    """Plan baslik metnini parse et.

    Plan basligi olarak kabul edilebilmesi icin metin kisa olmali; cok
    uzun teknik aciklama metinlerinde yanlislikla "ZEMIN/ÇATI" gibi
    kelimeler farkli context'te gecebilir.
    """
    if not text:
        return None
    s = text.strip()
    raw = s
    # Cok uzun metin = teknik aciklama, plan basligi olamaz
    if len(s) > 80:
        return None
    upper = s.upper()

    # Tipik kat: "2.VE 3. KAT" / "2,3.KAT"
    m_multi = _MULTI_KAT_RE.search(upper)
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

    if _BODRUM_RE.search(upper):
        return PlanLabelInfo(canonical_label="TEMEL", elevation_m=-3.0, raw=raw)
    if _ZEMIN_RE.search(upper):
        return PlanLabelInfo(canonical_label="0,00", elevation_m=0.0, raw=raw)
    if _CATI_RE.search(upper):
        # Cati plan: cogu zaman cati ust kotunu temsil eder; biz +15 varsayalim
        # ama metinden kotu da okuyalim
        m_kot = _KOT_RE.search(s)
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
    m_kat = _KAT_NUM_RE.search(upper)
    if m_kat:
        k = int(m_kat.group(1))
        elev = _kat_to_elevation(k, storey_h)
        return PlanLabelInfo(
            canonical_label=_elev_to_label(elev),
            elevation_m=elev,
            raw=raw,
        )
    # Kotu okuma (parantez icindeki)
    m_kot = _KOT_RE.search(s)
    if m_kot:
        elev = float(m_kot.group(1).replace(",", "."))
        return PlanLabelInfo(
            canonical_label=_elev_to_label(elev),
            elevation_m=elev,
            raw=raw,
        )
    return None


def _label_priority(info: "PlanLabelInfo") -> int:
    """Kanonik etiket bilgisinin guvenilirligi (yuksek > dusuk).

    Multi-kat (2.VE 3.KAT) en yuksek; sonra n.KAT/BODRUM/ZEMIN/CATI;
    en alt seviye saf kot bilgisi.

    Anchor kabulu icin metnin gercekten plan basligi olmasi sart:
    "PLAN" / "PLANI" kelimesi gecmeyen 'CATI' / 'BODRUM' geçen
    teknik notlar plan basligi degildir.
    """
    raw_upper = info.raw.upper()
    has_plan = "PLAN" in raw_upper or "PLANI" in raw_upper
    if info.multiplier > 1 and has_plan:
        return 100
    if has_plan and any(k in raw_upper for k in ("BODRUM", "ZEMIN", "ZEMİN")):
        return 90
    if has_plan and ("ÇATI" in raw_upper or "CATI" in raw_upper):
        return 80
    if has_plan and _KAT_NUM_RE.search(raw_upper):
        return 70
    return 30  # saf kot ya da plan basligi olmayan metin


def detect_title_anchors(
    texts: List[CadText],
    storey_h: float = 3.0,
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
        info = parse_plan_title(t.text, storey_h=storey_h)
        if info is None:
            continue
        if _label_priority(info) < 70:
            continue
        x, _ = t.insert
        anchors.append((x, info))
    anchors.sort(key=lambda a: a[0])
    return anchors


def detect_plan_multipliers(
    floor_plans: List[FloorPlan],
    texts: List[CadText],
    storey_h: float = 3.0,
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
        info = parse_plan_title(t.text, storey_h=storey_h)
        if info is None:
            continue
        priority = _label_priority(info)
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
