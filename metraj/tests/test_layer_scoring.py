"""Faz 1: ``score_layer`` ve ``detect_structural_layers`` skor sistemi testleri.

Hedef: katman adi regex'i tutmasa bile signal_hints (ad alias + renk) ve
geometrik imza (alan + aspect ratio) sinyallerinin birlikte dogru ElementKind
sectigini gostermek.

20+ varyasyon: standart Turkce, ingilizce, kisaltma, alfanumerik kodlar.
Hedef basari: >= %90 (18/20+ varyasyon dogru atanir).
"""
from __future__ import annotations

from typing import Optional

import pytest

from metraj.core.structural.layer_detection import (
    _SCORE_THRESHOLD,
    detect_structural_layers,
    score_layer,
)
from metraj.core.structural.layer_signals import LayerSignals


# Tipik gozlemlere dayali sentetik sinyaller (Kumluca'dan)
_COLUMN_SIG = LayerSignals(
    layer="X", color=2, poly_closed_count=120, closed_geom_count=120,
    area_min=0.10, area_max=2.0, area_median=0.20,
    aspect_min=1.0, aspect_max=4.0, aspect_median=1.8,
)
_PERDE_SIG = LayerSignals(
    layer="X", color=4, poly_closed_count=30, closed_geom_count=30,
    area_min=0.20, area_max=4.0, area_median=0.50,
    aspect_min=4.0, aspect_max=20.0, aspect_median=10.0,
)
_DOSEME_SIG = LayerSignals(
    layer="X", color=3, poly_closed_count=8, closed_geom_count=8,
    area_min=80.0, area_max=300.0, area_median=200.0,
    aspect_min=1.0, aspect_max=1.5, aspect_median=1.2,
)
_TEMEL_SIG = LayerSignals(
    layer="X", color=6, poly_closed_count=2, closed_geom_count=2,
    area_min=300.0, area_max=320.0, area_median=310.0,
    aspect_min=1.2, aspect_max=1.3, aspect_median=1.25,
)


SIGNAL_HINTS = {
    "name_aliases": {
        "column": ["K1", "K2", "K3", "BETONARME KOLON", "SP-COL", "STRUCT_COLUMN"],
        "shear_wall": ["S WALL", "P1", "P2", "STRUCT_WALL", "BETONARME PERDE"],
        "beam": ["S BEAMS", "B1", "B2", "STRUCT_BEAM"],
        "slab": ["DSME", "DOSME", "FLOOR_SLAB", "STRUCT_SLAB"],
        "foundation": ["TEMEL DUZ", "RADYE TEMEL", "FOUNDATION_MAT"],
        "lean_concrete": ["GROBET", "LEAN"],
    },
    "color_hints": {
        "column": [2],
        "shear_wall": [4],
        "beam": [1, 12, 13],
        "slab": [3, 92],
        "foundation": [6, 240],
        "lean_concrete": [240],
    },
}


def _best(scores: dict) -> Optional[str]:
    if not scores:
        return None
    kind, val = max(scores.items(), key=lambda kv: kv[1])
    return kind if val >= _SCORE_THRESHOLD else None


@pytest.mark.parametrize(
    "name, color, sig, expected",
    [
        # === KOLON (column) — 6 varyasyon ===
        ("KOLON NA", 2, _COLUMN_SIG, "column"),                # mevcut regex
        ("BETONARME_KOLON", 7, None, "column"),                # mevcut regex
        ("K1", 2, _COLUMN_SIG, "column"),                      # alias + renk + geom
        ("SP-COL-30x60", 2, _COLUMN_SIG, "column"),            # alias substring
        ("STRUCT_COLUMN", 7, _COLUMN_SIG, "column"),           # alias + geom
        ("S COLS", 7, None, "column"),                         # mevcut regex (S COLS)

        # === PERDE (shear_wall) — 4 varyasyon ===
        ("PERDE NA", 4, _PERDE_SIG, "shear_wall"),             # mevcut regex
        ("BETONARME PERDE", 4, _PERDE_SIG, "shear_wall"),
        ("S WALL", 7, _PERDE_SIG, "shear_wall"),               # alias + geom
        ("P1", 4, _PERDE_SIG, "shear_wall"),                   # alias + renk + geom

        # === KIRIS (beam) — 3 varyasyon ===
        ("KIRIS NA", 1, None, "beam"),                          # regex
        ("KİRİŞ NA", 12, None, "beam"),                         # regex (TR)
        ("S BEAMS", 13, None, "beam"),                          # regex + renk

        # === DOSEME (slab) — 3 varyasyon ===
        ("DOSEME NA", 3, _DOSEME_SIG, "slab"),                  # regex + renk + geom
        ("DÖŞEME NA", 3, _DOSEME_SIG, "slab"),
        ("FLOOR_SLAB", 3, _DOSEME_SIG, "slab"),                 # alias

        # === TEMEL/RADYE/GROBETON ===
        ("TEMEL NA", 6, _TEMEL_SIG, "foundation"),
        ("RADYE", 6, _TEMEL_SIG, "foundation"),                 # regex
        ("GROBETON NA", 240, _TEMEL_SIG, "lean_concrete"),      # alias + renk
        ("FOUNDATION_MAT", 7, _TEMEL_SIG, "foundation"),        # alias + geom

        # === PARAPET / ASANSOR / BACA ===
        ("30 CM PARAPET NA", 9, None, "parapet"),               # regex
        ("ASANSÖR KULE PERDE NA", 205, None, "elevator_shaft"), # regex
        ("BACA NA", 7, None, "chimney"),                        # regex
    ],
)
def test_score_layer_picks_expected_kind(name, color, sig, expected):
    """Her varyasyon icin en yuksek skorlu kind = beklenen."""
    scores = score_layer(name, color=color, signals=sig, signal_hints=SIGNAL_HINTS)
    chosen = _best(scores)
    assert chosen == expected, (
        f"score_layer('{name}', color={color}) -> {chosen!r} (beklenen: {expected!r}); "
        f"scores={dict(scores)}"
    )


def test_duplicate_layer_gets_penalty():
    """IZ_KOLON_PRY gibi cogalt katman, ad regex tutsa bile pratikte unmatched."""
    scores = score_layer("IZ_KOLON_PRY", color=2, signals=_COLUMN_SIG,
                          signal_hints=SIGNAL_HINTS)
    chosen = _best(scores)
    # Skor toplami: regex(0.6) + alias(0.5) + color(0.3) + geom(0.4) - duplicate(0.8) = 1.0
    # Yine threshold ustunde olabilir; ama detect_structural_layers'in
    # skip_duplicate_layers default'u zaten cogalt katmani atlatir.
    # Burada sadece cezanin uygulandigini gosteriyoruz:
    assert "column" in scores
    pure = score_layer("KOLON NA", color=2, signals=_COLUMN_SIG,
                        signal_hints=SIGNAL_HINTS)
    assert scores["column"] < pure["column"]


def test_unmatched_layer_below_threshold():
    """Hicbir sinyal tutmaz: ham katman adi -> unmatched."""
    scores = score_layer("AKS_CIZGI", color=7, signals=None, signal_hints=SIGNAL_HINTS)
    assert _best(scores) is None


def test_detect_layers_with_scoring_inverts_default_behavior():
    """signal_hints verilince score_layer devreye girer, regex-only tutmayan
    'K1' katmani 'column' olarak atanmali."""
    layers = ["K1", "AKS_CIZGI", "TEMEL NA"]
    inv = {l: {"polyline": 5, "hatch": 0, "block": 0, "text": 0, "line": 0}
           for l in layers}
    signals_map = {"K1": _COLUMN_SIG, "TEMEL NA": _TEMEL_SIG}
    colors = {"K1": 2, "AKS_CIZGI": 7, "TEMEL NA": 6}
    report = detect_structural_layers(
        layers, layer_inventory=inv,
        layer_signals=signals_map, layer_colors=colors,
        signal_hints=SIGNAL_HINTS,
    )
    assert report.layer_to_kind.get("K1") == "column"
    assert report.layer_to_kind.get("TEMEL NA") == "foundation"
    assert "AKS_CIZGI" in report.unmatched


def test_detect_layers_default_regex_only_backwards_compatible():
    """Sinyal verilmediginde eski regex davranisi: K1 unmatched."""
    layers = ["K1", "KOLON NA", "TEMEL NA"]
    report = detect_structural_layers(layers)
    assert "K1" in report.unmatched
    assert report.layer_to_kind["KOLON NA"] == "column"
    assert report.layer_to_kind["TEMEL NA"] == "foundation"
