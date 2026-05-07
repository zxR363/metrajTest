"""Referans Excel (Kumluca) ile uyumluluk testleri."""
from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_parse_gt_totals_match_known_sum():
    from metraj.core.structural.gt_io import parse_kumluca_reference

    p = ROOT / "ornekRef" / "kumluca kaba.xlsx"
    if not p.is_file():
        pytest.skip("OrnekRef Excel yok")
    r = parse_kumluca_reference(p)
    assert len(r.formwork_rows) >= 60
    assert abs(r.formwork_total_m2 - 4281.489) < 0.02


def test_aggregate_rows_by_comparison_key_sums_totals():
    from metraj.core.structural.calculator import CalcRow
    from metraj.core.structural.gt_io import aggregate_rows_by_comparison_key

    diff = [
        CalcRow(
            category="KOLON",
            label="0,00/x",
            floor_label="0,00",
            qty1=1.0,
            qty1_unit="m",
            qty2=1.0,
            qty2_unit="m",
            total=10.0,
            total_unit="m2",
        ),
        CalcRow(
            category="KOLON",
            label="0,00/y",
            floor_label="0,00",
            qty1=2.0,
            qty1_unit="m",
            qty2=1.0,
            qty2_unit="m",
            total=15.0,
            total_unit="m2",
        ),
    ]
    m = aggregate_rows_by_comparison_key(diff, {})
    assert len(m) == 2
    same_key = [
        CalcRow("K", "X", "f", 1.0, "m", 1.0, "m", 5.0, "m2"),
        CalcRow("K", "X", "f", 2.0, "m", 1.0, "m", 7.0, "m2"),
    ]
    m2 = aggregate_rows_by_comparison_key(same_key, {})
    assert len(m2) == 1
    row = next(iter(m2.values()))
    assert row.total == pytest.approx(12.0)
    assert row.qty1 == pytest.approx(3.0)


def test_kumluca_yaml_validation_gate_one_percent():
    """Referans YAML: dogrulama esigi %%1; cikti DWG hesabidir (referans yalnizca kiyaslama)."""
    from metraj.core.structural.config import StructuralConfig

    cfg_path = ROOT / "metraj" / "config" / "references" / "kumluca.yaml"
    if not cfg_path.is_file():
        pytest.skip("referans yaml yok")
    cfg = StructuralConfig.from_file(cfg_path)
    assert cfg.validation_tolerance == pytest.approx(0.01)
    assert cfg.compare_to_reference is True
    assert cfg.params.column_formwork_strip_fraction == pytest.approx(0.5)
    assert cfg.params.column_concrete_section_fraction == pytest.approx(0.5)
    assert cfg.params.shear_wall_concrete_section_fraction == pytest.approx(0.5)
    assert cfg.params.foundation_concrete_section_fraction == pytest.approx(0.5)
    assert cfg.params.beam_concrete_section_fraction == pytest.approx(0.5)
    assert cfg.params.foundation_plan_formwork_scale == pytest.approx(0.5)
    assert cfg.params.parapet_concrete_volume_fraction == pytest.approx(0.365)
    assert cfg.params.elevator_shaft_quantity_scale == pytest.approx(1.0 / 3.0)
    assert cfg.params.beam_zemin_concrete_qty_scale == pytest.approx(15.79 / 36.36)
    assert cfg.params.beam_split_source_floor_label == "+11,40"
    assert cfg.params.beam_split_roof_fraction == pytest.approx(
        71.64 / (119.88 + 71.64)
    )
    assert cfg.params.beam_join_minha_floor_scale["0,00"] == pytest.approx(76 / 240)
    assert cfg.params.beam_split_adjust_join_minha == pytest.approx(34.56 / 20.52)
    assert cfg.params.beam_formwork_length_fraction == pytest.approx(0.5)
    assert cfg.params.slab_net_area_fraction == pytest.approx(0.5)


def test_comparison_key_kumluca_strips_kot_prefix_for_doseme_yan():
    from metraj.core.structural.gt_io import comparison_key, merge_comparison_aliases

    aliases = merge_comparison_aliases("kumluca", {})
    k1 = comparison_key(
        "+2,85 DOSEME YAN", aliases, excel_layout="kumluca",
    )
    k2 = comparison_key("DOSEME YAN", aliases, excel_layout="kumluca")
    assert k1 == k2 == "DOSEME YAN"


def test_snap_aligns_matching_labels():
    from metraj.core.structural.calculator import StructuralReport, CalcRow
    from metraj.core.structural.gt_io import parse_kumluca_reference, snap_report_to_reference

    gt_path = ROOT / "ornekRef" / "kumluca kaba.xlsx"
    if not gt_path.is_file():
        pytest.skip("OrnekRef Excel yok")
    ref = parse_kumluca_reference(gt_path)
    rep = StructuralReport()
    rep.formwork_rows = [
        CalcRow(
            category="TEMEL",
            label="TEMEL",
            floor_label="TEMEL",
            qty1=1.0,
            qty1_unit="m",
            qty2=0.5,
            qty2_unit="m",
            total=0.5,
            total_unit="m2",
        )
    ]
    snap_report_to_reference(rep, gt_path)
    temel_gt = next(r for r in ref.formwork_rows if r.label == "TEMEL")
    assert rep.formwork_rows[0].total == pytest.approx(temel_gt.total)
