"""Faz 4 GUI: calibration_wizard non-GUI helper testleri.

QDialog'un kendisi otomatize edilemez (manual smoke test gerekir); ancak
veri-flow yardimcilari (``apply_user_edits_to_params``, ``collect_editable_fields``)
saf Python ve tam test edilebilir.
"""
from __future__ import annotations

import pytest

from metraj.core.structural.calculator import CalcParams
from metraj.core.structural.profile_fitter import FitFieldResult, FitResult


def _mock_fit_result_with_fields() -> FitResult:
    cp = CalcParams(
        column_concrete_section_fraction=0.5,
        slab_net_area_fraction=0.51,
    )
    return FitResult(
        fitted_params=cp,
        field_results=[
            FitFieldResult(
                field_name="column_concrete_section_fraction",
                fitted_value=0.5,
                baseline_total=300.0,
                reference_total=150.0,
                matched_rows=6,
            ),
            FitFieldResult(
                field_name="slab_net_area_fraction",
                fitted_value=0.51,
                baseline_total=3000.0,
                reference_total=1530.0,
                matched_rows=42,
            ),
        ],
    )


def test_collect_editable_fields_extracts_rows():
    from metraj.app.calibration_wizard import collect_editable_fields
    res = _mock_fit_result_with_fields()
    rows = collect_editable_fields(res)
    assert len(rows) == 2
    assert rows[0]["field_name"] == "column_concrete_section_fraction"
    assert rows[0]["fitted_value"] == pytest.approx(0.5)
    assert rows[0]["matched_rows"] == 6
    assert rows[1]["field_name"] == "slab_net_area_fraction"
    assert rows[1]["fitted_value"] == pytest.approx(0.51)


def test_apply_user_edits_updates_calcparams():
    from metraj.app.calibration_wizard import apply_user_edits_to_params
    base = CalcParams(
        column_concrete_section_fraction=0.5,
        slab_net_area_fraction=0.5,
    )
    edits = {
        "column_concrete_section_fraction": 0.48,
        "slab_net_area_fraction": 0.52,
    }
    out = apply_user_edits_to_params(base, edits)
    assert out.column_concrete_section_fraction == pytest.approx(0.48)
    assert out.slab_net_area_fraction == pytest.approx(0.52)
    # base unchanged (immutable semantic)
    assert base.column_concrete_section_fraction == pytest.approx(0.5)


def test_apply_user_edits_ignores_unknown_field():
    from metraj.app.calibration_wizard import apply_user_edits_to_params
    base = CalcParams()
    out = apply_user_edits_to_params(base, {"nonexistent_field": 1.23})
    # Patlamamali; out base ile ayni olmali
    assert out.column_concrete_section_fraction == base.column_concrete_section_fraction


def test_apply_user_edits_ignores_non_float():
    from metraj.app.calibration_wizard import apply_user_edits_to_params
    base = CalcParams(slab_net_area_fraction=0.5)
    out = apply_user_edits_to_params(base, {"slab_net_area_fraction": "abc"})
    assert out.slab_net_area_fraction == pytest.approx(0.5)


def test_apply_user_edits_preserves_dict_fields():
    """Kullanici sadece global scale degerlerini duzenler; dict alanlar dokunulmaz."""
    from metraj.app.calibration_wizard import apply_user_edits_to_params
    base = CalcParams(
        slab_net_area_fraction=0.5,
        doseme_net_scale_by_floor_label={"0,00": 1.02, "+2,85": 1.03},
    )
    out = apply_user_edits_to_params(base, {"slab_net_area_fraction": 0.55})
    assert out.slab_net_area_fraction == pytest.approx(0.55)
    assert out.doseme_net_scale_by_floor_label == {"0,00": 1.02, "+2,85": 1.03}


def test_module_import_pyside_flag():
    """PySide6 mevcut ortamda PYSIDE_AVAILABLE True olmali."""
    from metraj.app import calibration_wizard
    assert hasattr(calibration_wizard, "PYSIDE_AVAILABLE")
    # Bu test ortaminda PySide6 kurulu, ama varsa-yoksa import basariyla cozulmeli
    assert isinstance(calibration_wizard.PYSIDE_AVAILABLE, bool)


def test_launch_wizard_raises_without_pyside(monkeypatch):
    """PySide6 yoksa launch_wizard RuntimeError firlatmali."""
    from metraj.app import calibration_wizard
    monkeypatch.setattr(calibration_wizard, "PYSIDE_AVAILABLE", False)
    with pytest.raises(RuntimeError, match="PySide6"):
        calibration_wizard.launch_wizard()
