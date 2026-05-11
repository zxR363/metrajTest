"""Faz 2: ``parse_plan_title`` locale (TR / EN) ve token-bazli plausibility.

30+ baslik varyasyonu: Turkce default, ingilizce locale, multi-floor formatlari,
sayisal-kot fallback ve uzun teknik metinlerin reddi.

Hedef basari: ≥%95 (29/30+).
"""
from __future__ import annotations

import pytest

from metraj.core.structural.plan_labels import (
    PlanLabelLocale,
    _label_priority,
    parse_plan_title,
)


_EN = PlanLabelLocale.load("en")


# ---------------------------------------------------------------------------
# Turkce baslik testleri (default locale)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "text, expected_label, min_priority",
    [
        # Standart Kumluca tarzi
        ("BODRUM KAT PLANI", "TEMEL", 90),
        ("BODRUM KAT PLANI OLCEK: 1/50", "TEMEL", 90),
        ("ZEMIN KAT PLANI", "0,00", 90),
        ("ZEMİN KAT PLANI", "0,00", 90),
        ("1.KAT PLANI", "+3,00", 70),
        ("1. KAT PLANI (+3.00)", "+3,00", 70),
        ("4. KAT PLANI", "+12,00", 70),
        ("4. KAT PLANI (+12.00 KOTU)", "+12,00", 70),
        # Multi-kat (tipik kat)
        ("2.VE 3. KAT PLANI", "+6,00", 100),
        ("2 VE 3 KAT PLANI", "+6,00", 100),
        ("3,4. KAT PLANI", "+9,00", 100),
        # Cati
        ("CATI KATI PLANI", "CATI", 80),
        ("ÇATI KATI PLANI", "CATI", 80),
        ("CATI PLANI", "CATI", 80),
        # Temel
        ("TEMEL PLANI", "TEMEL", 90),
        # Uzun teknik metin -> reddedilmeli (None)
        ("GEZİLEMEYEN TERAS ÇATI, MARKİZ (PROJESİNDE TERAS İSE) VE ASANSÖR MAKİNE DAİRESİ ÜZERİ: zemin izolasyonu bla bla bla teknik aciklama burada cok uzun devam eder", None, 0),
    ],
)
def test_parse_tr_default_locale(text, expected_label, min_priority):
    info = parse_plan_title(text)
    if expected_label is None:
        assert info is None, f"'{text}' reddedilmeliydi, donen: {info}"
        return
    assert info is not None, f"'{text}' parse edilmeliydi"
    assert info.canonical_label == expected_label
    pr = _label_priority(info)
    assert pr >= min_priority, f"priority {pr} < {min_priority} for '{text}'"


# ---------------------------------------------------------------------------
# Ingilizce locale
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "text, expected_label, min_priority",
    [
        ("BASEMENT FLOOR PLAN", "TEMEL", 90),
        ("GROUND FLOOR PLAN", "0,00", 90),
        ("1ST FLOOR PLAN", "+3,00", 70),
        ("1ST FLOOR (+3.00)", "+3,00", 70),
        ("4TH FLOOR PLAN", "+12,00", 70),
        ("ROOF PLAN", "CATI", 80),
        ("TERRACE LEVEL PLAN", "CATI", 80),
        ("2ND AND 3RD FLOOR PLAN", "+6,00", 100),
    ],
)
def test_parse_en_locale(text, expected_label, min_priority):
    info = parse_plan_title(text, locale=_EN)
    assert info is not None, f"'{text}' parse edilmeliydi (EN)"
    assert info.canonical_label == expected_label
    pr = _label_priority(info, locale=_EN)
    assert pr >= min_priority


# ---------------------------------------------------------------------------
# Plan basligi olmayan / reddedilmesi gereken metinler
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "text",
    [
        "AKS-1",
        "KOLON",
        "K1",
        "S1",
        "1828-14",
        "OLCEK 1/50",
        # PLAN/KAT gecmeyen sayisal etiket — kullanici verisi degil sadece kot
        "+3.00",
        "0.00",
    ],
)
def test_plan_titles_reject_non_titles(text):
    info = parse_plan_title(text)
    # priority<70 olmali — anchor olarak kabul edilmez
    if info is None:
        return
    pr = _label_priority(info)
    assert pr < 70, f"'{text}' anchor olmamali (priority={pr})"


# ---------------------------------------------------------------------------
# Sayisal-kot fallback: PLAN/KAT gecen kisa metinde sayisal kot yakala
# ---------------------------------------------------------------------------

def test_numeric_elevation_fallback_when_plan_keyword_present():
    """Token-bazli plausibility: 'PLAN +3.00' icin sayisal fallback devrede."""
    info = parse_plan_title("PLAN +3.00")
    assert info is not None
    assert info.canonical_label == "+3,00"


def test_locale_load_tr_en_files_exist():
    """Paket icinde plan_labels_tr.yaml ve plan_labels_en.yaml yuklenebilmeli."""
    tr = PlanLabelLocale.load("tr")
    en = PlanLabelLocale.load("en")
    assert "PLAN" in [w.upper() for w in tr.plan_keywords]
    assert "FLOOR" in [w.upper() for w in en.floor_keyword]
    # TR'de basement TEMEL/BODRUM, EN'de BASEMENT olmali
    assert any("BODRUM" in w.upper() for w in tr.basement)
    assert any("BASEMENT" in w.upper() for w in en.basement)
