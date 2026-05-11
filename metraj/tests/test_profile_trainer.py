"""Faz 6: profile_trainer mock-fit testleri.

train_profiles_from_pairs pahali (her proje icin pipeline kosumu). Bu testler
``build_trained_profile_from_fit_results``'i kullanarak agregasyon mantigini
hizli (no-pipeline) cosurarak dogrular.
"""
from __future__ import annotations

import pytest

from metraj.core.structural.calculator import CalcParams
from metraj.core.structural.profile_fitter import FitFieldResult, FitResult


def _mock_fit_result(
    scales: dict, floor_scales: dict | None = None,
) -> FitResult:
    """Sentetik FitResult: yalniz fit edilen alanlari dolu, dict alanlar opsiyonel."""
    field_results = []
    for name, val in scales.items():
        field_results.append(FitFieldResult(
            field_name=name, fitted_value=val,
            baseline_total=100.0, reference_total=100.0 * val,
            matched_rows=5,
        ))
    cp = CalcParams()
    for k, v in scales.items():
        if hasattr(cp, k):
            setattr(cp, k, v)
    if floor_scales:
        for k, v in floor_scales.items():
            if hasattr(cp, k):
                setattr(cp, k, dict(v))
    return FitResult(
        fitted_params=cp,
        field_results=field_results,
        baseline_formwork_total=100, baseline_concrete_total=50,
        reference_formwork_total=50, reference_concrete_total=25,
    )


def test_median_aggregation_three_projects():
    """3 projede aynı alan: 0.48, 0.50, 0.52 -> median=0.50."""
    from metraj.core.learning.profile_trainer import (
        build_trained_profile_from_fit_results,
    )
    fits = [
        _mock_fit_result({"column_concrete_section_fraction": 0.48}),
        _mock_fit_result({"column_concrete_section_fraction": 0.50}),
        _mock_fit_result({"column_concrete_section_fraction": 0.52}),
    ]
    profile = build_trained_profile_from_fit_results(fits, ["P1", "P2", "P3"])
    assert profile.project_count == 3
    assert profile.field_stats["column_concrete_section_fraction"].median == pytest.approx(0.50)
    assert profile.fitted_params.column_concrete_section_fraction == pytest.approx(0.50)


def test_outlier_does_not_distort_median():
    """5 proje: 4'u ~0.5, 1'i 5.0 outlier; median yine ~0.5."""
    from metraj.core.learning.profile_trainer import (
        build_trained_profile_from_fit_results,
    )
    fits = [
        _mock_fit_result({"slab_net_area_fraction": v})
        for v in (0.48, 0.50, 0.52, 0.49, 5.00)  # son outlier
    ]
    profile = build_trained_profile_from_fit_results(
        fits, [f"P{i}" for i in range(5)],
    )
    fs = profile.field_stats["slab_net_area_fraction"]
    assert fs.median == pytest.approx(0.50)
    # Outlier tespit (Tukey fence n>=4)
    assert 4 in fs.outlier_project_indices  # 5. proje (index 4) outlier


def test_floor_dict_aggregation_per_floor_median():
    """3 projede ayni dict alani, her katta farkli degerler -> per-floor median."""
    from metraj.core.learning.profile_trainer import (
        build_trained_profile_from_fit_results,
    )
    fits = [
        _mock_fit_result(
            {"slab_net_area_fraction": 0.5},
            floor_scales={"doseme_net_scale_by_floor_label":
                          {"0,00": 1.02, "+2,85": 1.01}},
        ),
        _mock_fit_result(
            {"slab_net_area_fraction": 0.5},
            floor_scales={"doseme_net_scale_by_floor_label":
                          {"0,00": 1.04, "+2,85": 1.03}},
        ),
        _mock_fit_result(
            {"slab_net_area_fraction": 0.5},
            floor_scales={"doseme_net_scale_by_floor_label":
                          {"0,00": 1.06, "+2,85": 1.05}},
        ),
    ]
    profile = build_trained_profile_from_fit_results(fits, ["P1", "P2", "P3"])
    assert "doseme_net_scale_by_floor_label" in profile.floor_dict_stats
    fd = profile.floor_dict_stats["doseme_net_scale_by_floor_label"]
    assert fd.per_floor_median["0,00"] == pytest.approx(1.04)
    assert fd.per_floor_median["+2,85"] == pytest.approx(1.03)
    # CalcParams'a yansidi
    assert profile.fitted_params.doseme_net_scale_by_floor_label["0,00"] == pytest.approx(1.04)


def test_floor_with_partial_projects_takes_available_median():
    """Bazi projeler bir kat icin scale uretmemis -> sadece veren projeler median'a girer."""
    from metraj.core.learning.profile_trainer import (
        build_trained_profile_from_fit_results,
    )
    fits = [
        _mock_fit_result(
            {"slab_net_area_fraction": 0.5},
            floor_scales={"doseme_net_scale_by_floor_label": {"0,00": 1.05}},
        ),
        _mock_fit_result(
            {"slab_net_area_fraction": 0.5},
            floor_scales={"doseme_net_scale_by_floor_label":
                          {"0,00": 1.05, "+2,85": 0.98}},
        ),
    ]
    profile = build_trained_profile_from_fit_results(fits, ["P1", "P2"])
    fd = profile.floor_dict_stats["doseme_net_scale_by_floor_label"]
    assert fd.per_floor_median["0,00"] == pytest.approx(1.05)
    # +2,85 sadece P2'de var; median = tek deger
    assert fd.per_floor_median["+2,85"] == pytest.approx(0.98)


def test_single_project_still_produces_trained_profile():
    """1 proje: median = tek deger; outlier tespit edilemez (n<4)."""
    from metraj.core.learning.profile_trainer import (
        build_trained_profile_from_fit_results,
    )
    fits = [_mock_fit_result({"column_formwork_strip_fraction": 0.45})]
    profile = build_trained_profile_from_fit_results(fits, ["Solo"])
    fs = profile.field_stats["column_formwork_strip_fraction"]
    assert fs.median == pytest.approx(0.45)
    assert fs.std == 0.0
    assert fs.outlier_project_indices == []


def test_report_contains_project_names_and_field_medians():
    from metraj.core.learning.profile_trainer import (
        build_trained_profile_from_fit_results,
    )
    fits = [
        _mock_fit_result({"slab_net_area_fraction": 0.50}),
        _mock_fit_result({"slab_net_area_fraction": 0.52}),
    ]
    profile = build_trained_profile_from_fit_results(fits, ["Alpha", "Beta"])
    assert "Alpha" in profile.report
    assert "Beta" in profile.report
    assert "slab_net_area_fraction" in profile.report
    assert "Proje sayisi: 2" in profile.report


def test_dump_trained_yaml_round_trip(tmp_path):
    """train_profiles_from_pairs cikisini dump_fitted_yaml ile yazip yeniden yukle."""
    from metraj.core.learning.profile_trainer import (
        build_trained_profile_from_fit_results,
    )
    from metraj.core.structural.config import StructuralConfig
    from metraj.core.structural.profile_fitter import dump_fitted_yaml

    fits = [
        _mock_fit_result(
            {"slab_net_area_fraction": 0.50,
             "column_concrete_section_fraction": 0.49},
            floor_scales={"doseme_net_scale_by_floor_label":
                          {"0,00": 1.02, "+2,85": 1.01}},
        ),
        _mock_fit_result(
            {"slab_net_area_fraction": 0.51,
             "column_concrete_section_fraction": 0.50},
            floor_scales={"doseme_net_scale_by_floor_label":
                          {"0,00": 1.04, "+2,85": 1.03}},
        ),
    ]
    profile = build_trained_profile_from_fit_results(fits, ["P1", "P2"])
    out = tmp_path / "trained.yaml"
    dump_fitted_yaml(profile.fitted_params, out, project_name="Trained N=2")

    cfg = StructuralConfig.from_file(out)
    assert cfg.params.slab_net_area_fraction == pytest.approx(0.505)
    assert cfg.params.column_concrete_section_fraction == pytest.approx(0.495)
    assert cfg.params.doseme_net_scale_by_floor_label["0,00"] == pytest.approx(1.03)
