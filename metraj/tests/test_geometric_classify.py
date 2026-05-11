"""Faz 3: ``geometric_classify`` + ``find_classification_conflicts`` testleri.

Sentetik elemanlarla 15+ varyasyon. Hedef: layer bilgisi olmadan geometri
sinyalleriyle ≥%85 dogru kind tahmini + hibrit uyari listesi calismasi.
"""
from __future__ import annotations

from typing import List

import pytest
from shapely.geometry import LineString, Polygon

from metraj.core.structural.classify import (
    GeometricThresholds,
    find_classification_conflicts,
    geometric_classify,
)
from metraj.core.structural.elements import StructuralElement


def _poly_element(kind: str, width: float, height: float,
                   x: float = 0, y: float = 0, layer: str = "TEST") -> StructuralElement:
    poly = Polygon([
        (x, y), (x + width, y), (x + width, y + height), (x, y + height),
    ])
    return StructuralElement(
        kind=kind, layer=layer, geom=poly,
        area_m2=poly.area, perimeter_m=poly.length, length_m=0.0,
    )


def _line_element(kind: str, length: float, layer: str = "TEST") -> StructuralElement:
    ls = LineString([(0, 0), (length, 0)])
    return StructuralElement(
        kind=kind, layer=layer, geom=ls,
        area_m2=0.0, perimeter_m=0.0, length_m=ls.length,
    )


# ---------------------------------------------------------------------------
# Geometrik kind tahmini — layer kind GORMEZDEN GELINIR
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "name, element, expected_kind",
    [
        # KOLON: kucuk + kompakt (Kumluca tipik 0.7x0.5)
        ("col_70x50", _poly_element("foo", 0.7, 0.5), "column"),
        ("col_60x60", _poly_element("foo", 0.6, 0.6), "column"),
        ("col_30x30", _poly_element("foo", 0.3, 0.3), "column"),
        ("col_100x60", _poly_element("foo", 1.0, 0.6), "column"),  # aspect ~1.66
        # PERDE: uzun-ince (aspect >> 8)
        ("wall_5x0.25", _poly_element("foo", 5.0, 0.25), "shear_wall"),  # aspect 20
        ("wall_4x0.3", _poly_element("foo", 4.0, 0.3), "shear_wall"),    # aspect ~13
        ("wall_10x0.4", _poly_element("foo", 10.0, 0.4), "shear_wall"),  # aspect 25
        # DOSEME / TEMEL: buyuk alan kompakt
        ("slab_15x10", _poly_element("foo", 15.0, 10.0), "slab"),         # 150 m2, asp 1.5
        ("temel_20x15", _poly_element("foo", 20.0, 15.0), "foundation"),  # 300 m2
        # Kiris: acik LINE
        ("beam_4m", _line_element("foo", 4.0), "beam"),
        ("beam_2m", _line_element("foo", 2.0), "beam"),
    ],
)
def test_geometric_classify_picks_correct_kind(name, element, expected_kind):
    gc = geometric_classify(element)
    assert gc.kind == expected_kind, (
        f"{name}: gc.kind={gc.kind!r} (beklenen {expected_kind!r}); "
        f"reason='{gc.reason}', conf={gc.confidence:.2f}"
    )
    # Confidence min esigin uzerinde olmali
    th = GeometricThresholds()
    assert gc.confidence >= th.min_confidence, (
        f"{name}: confidence {gc.confidence:.2f} < {th.min_confidence}"
    )


def test_kuskulu_aspect_range_returns_none():
    """2.5 < aspect < 8 araligi -> belirsiz."""
    # 1m x 0.25m = aspect 4.0 (kuskulu)
    el = _poly_element("foo", 1.0, 0.25)
    gc = geometric_classify(el)
    assert gc.kind is None
    assert gc.confidence < 0.5


def test_short_open_line_uncertain():
    el = _line_element("foo", 0.5)  # 0.5m kisa
    gc = geometric_classify(el)
    assert gc.kind is None


def test_thresholds_override():
    """Eşikler override edildiginde davranis degisir."""
    # Default'ta 1.5m x 0.3m -> aspect 5 (kuskulu)
    el = _poly_element("foo", 1.5, 0.3)
    assert geometric_classify(el).kind is None
    # wall_min_aspect=4 ise simdi perde
    th = GeometricThresholds(wall_min_aspect=4.0)
    assert geometric_classify(el, th).kind == "shear_wall"


# ---------------------------------------------------------------------------
# Hibrit kontrol — sessiz overwrite YOK, sadece uyari
# ---------------------------------------------------------------------------

def test_conflicts_only_when_layer_kind_differs_significantly():
    """Layer kolon ama geometri perde -> conflict uretilir."""
    # 5m x 0.25m polygon, layer kolon olarak isaretli (yanlis)
    wall_as_column = _poly_element("column", 5.0, 0.25)
    # 0.7m x 0.5m polygon, layer kolon, geometri de kolon (dogru, conflict yok)
    real_column = _poly_element("column", 0.7, 0.5)

    elements = [wall_as_column, real_column]
    conflicts = find_classification_conflicts(elements)
    assert len(conflicts) == 1
    c = conflicts[0]
    assert c.layer_kind == "column"
    assert c.geometric_kind == "shear_wall"
    assert c.confidence >= 0.5
    # element.kind degismedi (sessiz overwrite yok)
    assert wall_as_column.kind == "column"


def test_no_conflict_for_excluded_kinds():
    """parapet/elevator_shaft/chimney layer kind'leri sessiz birakilir."""
    # 0.7x0.5 polygon, layer parapet (geometri kolon) -> conflict reported?
    parapet_as_col_geom = _poly_element("parapet", 0.7, 0.5)
    conflicts = find_classification_conflicts([parapet_as_col_geom])
    assert conflicts == []


def test_kumluca_diagnostic_signature_kolon_layer_aspect_19_flagged():
    """Faz 0 diagnostics'te gozlemlenen: KOLON NA katmaninda aspect=19
    eleman -> geometric_classify perde demeli, conflict raporlanmali."""
    # Sentetik: 19 m x 1 m polygon, layer "KOLON NA" kolon kind
    fake_kolon = _poly_element("column", 19.0, 1.0, layer="KOLON NA")
    conflicts = find_classification_conflicts([fake_kolon])
    assert len(conflicts) == 1
    assert conflicts[0].geometric_kind == "shear_wall"
    assert conflicts[0].aspect_ratio >= 8.0


def test_open_line_beam_layer_no_conflict():
    """Layer beam + geometric_classify beam -> conflict yok."""
    el = _line_element("beam", 4.0)
    assert find_classification_conflicts([el]) == []
