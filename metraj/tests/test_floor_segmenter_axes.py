"""Faz 2: ``detect_plan_groups(axis=...)`` ve ``assign_elements_to_plans``
yatay (Kumluca-tipi) ve dusey layout testleri.
"""
from __future__ import annotations

from typing import List

import pytest
from shapely.geometry import Polygon

from metraj.core.structural.elements import StructuralElement
from metraj.core.structural.floor_segmenter import (
    assign_elements_to_plans,
    detect_plan_groups,
)


def _column(x: float, y: float, kind: str = "column", side: float = 0.6) -> StructuralElement:
    poly = Polygon([
        (x, y), (x + side, y), (x + side, y + side), (x, y + side),
    ])
    return StructuralElement(
        kind=kind, layer="KOLON NA", geom=poly,
        area_m2=poly.area, perimeter_m=poly.length,
    )


def _floor_x_layout(n_floors: int = 5, per_floor: int = 10,
                     plan_width: float = 20.0, gap: float = 8.0) -> List[StructuralElement]:
    """Yatay layout: planlar sol-saga sirali. n_floors plan, her plan 10 kolon."""
    out: List[StructuralElement] = []
    for f in range(n_floors):
        x0 = f * (plan_width + gap)
        for i in range(per_floor):
            x = x0 + (i % 5) * (plan_width / 5)
            y = (i // 5) * 5
            out.append(_column(x, y))
    return out


def _floor_y_layout(n_floors: int = 5, per_floor: int = 10,
                     plan_height: float = 20.0, gap: float = 8.0) -> List[StructuralElement]:
    """Dusey layout: planlar alt-ustte sirali."""
    out: List[StructuralElement] = []
    for f in range(n_floors):
        y0 = f * (plan_height + gap)
        for i in range(per_floor):
            x = (i % 5) * 4.0
            y = y0 + (i // 5) * 5
            out.append(_column(x, y))
    return out


def test_horizontal_layout_x_axis_clusters_correctly():
    elements = _floor_x_layout(n_floors=5, per_floor=10)
    plans = detect_plan_groups(elements, expected_floor_count=5, axis="x")
    assert len(plans) == 5
    # Planlar x sirali; xmin'ler artiyor olmali
    xs_min = [p.bbox[0] for p in plans]
    assert xs_min == sorted(xs_min)


def test_vertical_layout_y_axis_clusters_correctly():
    elements = _floor_y_layout(n_floors=5, per_floor=10)
    plans = detect_plan_groups(elements, expected_floor_count=5, axis="y")
    assert len(plans) == 5
    # Planlar y sirali; ymin'ler artiyor olmali
    ys_min = [p.bbox[1] for p in plans]
    assert ys_min == sorted(ys_min)


def test_auto_axis_picks_correct_layout_for_horizontal():
    elements = _floor_x_layout(n_floors=4, per_floor=8)
    plans = detect_plan_groups(elements, expected_floor_count=4, axis="auto")
    assert len(plans) == 4


def test_auto_axis_picks_correct_layout_for_vertical():
    elements = _floor_y_layout(n_floors=4, per_floor=8)
    plans = detect_plan_groups(elements, expected_floor_count=4, axis="auto")
    assert len(plans) == 4


def test_assign_elements_horizontal():
    elements = _floor_x_layout(n_floors=3, per_floor=10)
    plans = detect_plan_groups(elements, expected_floor_count=3, axis="x")
    fps, unassigned = assign_elements_to_plans(elements, plans, axis="x")
    assert len(fps) == 3
    # her plan kendi yarisindaki kolonlari almali
    assert sum(len(fp.elements) for fp in fps) + len(unassigned) == len(elements)
    assert all(len(fp.elements) > 0 for fp in fps)


def test_assign_elements_vertical():
    elements = _floor_y_layout(n_floors=3, per_floor=10)
    plans = detect_plan_groups(elements, expected_floor_count=3, axis="y")
    fps, unassigned = assign_elements_to_plans(elements, plans, axis="y")
    assert len(fps) == 3
    assert sum(len(fp.elements) for fp in fps) + len(unassigned) == len(elements)
    # alt-ust sirali olmali (y sirasi)
    ys = [fp.bbox[1] for fp in fps]
    assert ys == sorted(ys)


def test_unknown_axis_falls_back_to_x():
    """Bilinmeyen axis 'x' default'una duser; uyari log uretir ama patlamamali."""
    elements = _floor_x_layout(n_floors=3, per_floor=10)
    plans = detect_plan_groups(elements, expected_floor_count=3, axis="diagonal")
    assert len(plans) == 3
