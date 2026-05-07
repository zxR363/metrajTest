"""Revision comparator unit tests."""
from __future__ import annotations

from shapely.geometry import Polygon

from metraj.core.pozlar import IcmalRow, PozTotals
from metraj.core.quantities import RoomQuantities
from metraj.core.reports import RevisionComparator
from metraj.core.rooms import Room


def _room(code: str, w: float, h: float, height: float = 4.3) -> Room:
    poly = Polygon([(0, 0), (w, 0), (w, h), (0, h)])
    return Room(
        code=code, name=code, floor=code.split("-")[0],
        polygon=poly, label_point=(w / 2, h / 2), height=height,
    )


def _qty(room: Room) -> RoomQuantities:
    return RoomQuantities(
        room=room,
        net_floor_m2=room.area,
        net_ceiling_m2=room.area,
        net_wall_m2=room.perimeter * room.height,
        net_skirting_m=room.perimeter,
    )


def test_revision_detects_added_removed_and_resized() -> None:
    old_qs = [_qty(_room("Z-01", 4, 5)), _qty(_room("Z-02", 3, 3))]
    new_qs = [_qty(_room("Z-01", 4, 5)), _qty(_room("Z-03", 5, 5))]
    old_icmal = PozTotals(rows=[
        IcmalRow("15.385.1028", "DOSEME", "Porselen", "m2", 100.0, 720.0)
    ])
    new_icmal = PozTotals(rows=[
        IcmalRow("15.385.1028", "DOSEME", "Porselen", "m2", 130.0, 720.0)
    ])
    report = RevisionComparator(area_threshold_pct=1.0).compare(
        old_qs, new_qs, old_icmal, new_icmal)
    assert any(q.room.code == "Z-03" for q in report.rooms_added)
    assert any(q.room.code == "Z-02" for q in report.rooms_removed)
    assert any(d.poz_no == "15.385.1028" for d in report.pozlar_changed)
    assert report.grand_total_diff > 0


def test_revision_threshold_filters_small_changes() -> None:
    old_qs = [_qty(_room("Z-01", 4, 5))]
    new_qs = [_qty(_room("Z-01", 4.01, 5))]
    old_icmal = PozTotals(rows=[
        IcmalRow("15.385.1028", "DOSEME", "Porselen", "m2", 20.0, 720.0)
    ])
    new_icmal = PozTotals(rows=[
        IcmalRow("15.385.1028", "DOSEME", "Porselen", "m2", 20.05, 720.0)
    ])
    report = RevisionComparator(area_threshold_pct=5.0,
                                tutar_threshold=100.0).compare(
        old_qs, new_qs, old_icmal, new_icmal)
    assert not report.rooms_changed
    assert not report.pozlar_changed
