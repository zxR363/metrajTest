"""Faz 4: profile_fitter Kumluca uctan uca testi.

Kumluca DXF + Kumluca Excel verildiginde:
* Fit edilen kritik CalcParams alanlari Kumluca elle-yazilmis yaml'a yakin olmali.
* Fit edilen profil pipeline'a yuklenip kosulunca KALIP/BETON toplami referansa
  yakin olmali (saf geometri %200/%361'den dramatik iyilesme).

Tek-param fit'in dogal limitleri (beam_split_*, kat-bazli dict alanlar yoktur)
nedeniyle satir-bazi sapma %1 hedefine ulasmayabilir; toplam sapma hedefimiz
%10 altinda (yeni proje icin makul ilk-vurus).
"""
from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _kumluca_inputs():
    cad = ROOT / "ornekRef" / "kumluca kaba ataşman na.dxf"
    ref = ROOT / "ornekRef" / "kumluca kaba.xlsx"
    if not cad.is_file() or not ref.is_file():
        pytest.skip("Kumluca CAD/Excel girdileri yok")
    return cad, ref


@pytest.mark.slow
def test_kumluca_fit_recovers_known_scale_values(kumluca_fit_result):
    """Kumluca DXF/Excel ile fit edilen ana ölçek alanlari Kumluca yaml ile
    yakin (kritik alanlar ±%10). Paylasilan ``kumluca_fit_result`` fixture."""
    fp = kumluca_fit_result.fitted_params

    # Kumluca'da elle yazilmis ana scale'ler hepsi 0.5; fit bunlari yakalamali.
    assert 0.4 <= fp.column_formwork_strip_fraction <= 0.55, fp.column_formwork_strip_fraction
    assert 0.45 <= fp.column_concrete_section_fraction <= 0.55, fp.column_concrete_section_fraction
    assert 0.45 <= fp.shear_wall_concrete_section_fraction <= 0.55, fp.shear_wall_concrete_section_fraction
    assert 0.45 <= fp.foundation_concrete_section_fraction <= 0.55, fp.foundation_concrete_section_fraction
    assert 0.45 <= fp.foundation_plan_formwork_scale <= 0.55, fp.foundation_plan_formwork_scale
    assert 0.45 <= fp.slab_net_area_fraction <= 0.55, fp.slab_net_area_fraction

    # YAML dosyasi yazilmis ve StructuralConfig.from_file ile geri yuklenebilmeli
    from metraj.core.structural.config import StructuralConfig
    assert kumluca_fit_result.yaml_path is not None
    cfg = StructuralConfig.from_file(kumluca_fit_result.yaml_path)
    assert cfg.excel_layout == "kumluca"
    assert cfg.compare_to_reference is True
    assert cfg.params.column_concrete_section_fraction == pytest.approx(
        fp.column_concrete_section_fraction
    )


@pytest.mark.slow
def test_kumluca_fitted_profile_reduces_total_deviation(kumluca_fit_result, kumluca_paths, tmp_path):
    """Faz 4 v2: iki-asamali fit ile KALIP toplam sapma <%1, BETON <%10."""
    from metraj.core.structural.config import StructuralConfig
    from metraj.core.structural.pipeline import StructuralPipeline

    cad, _ref, _yaml = kumluca_paths
    cfg = StructuralConfig.from_file(kumluca_fit_result.yaml_path)
    pipe = StructuralPipeline(config=cfg)
    res = pipe.run(cad_path=cad, output_dir=tmp_path / "run",
                   write_excel=False, write_diagnostics=False)

    ref_form = 4281.49
    ref_conc = 798.75
    form_err = abs(res.report.formwork_total_m2 - ref_form) / ref_form
    conc_err = abs(res.report.concrete_total_m3 - ref_conc) / ref_conc

    # Faz 4 v2: KALIP toplam sapma %1 altinda olmali (gozlemlenen ~%0.23).
    assert form_err < 0.01, (
        f"KALIP toplam sapma {form_err*100:.2f}% > %1; baz cizgi ~%0.23"
    )
    # BETON: %10 altinda (gozlemlenen ~%8.96; beam_split_* henuz fit edilmiyor).
    assert conc_err < 0.10, (
        f"BETON toplam sapma {conc_err*100:.2f}% > %10; baz cizgi ~%8.96"
    )


@pytest.mark.slow
def test_two_stage_fit_produces_floor_dict_entries(kumluca_fit_result):
    """Faz 4 v2: ikinci asama Kumluca'da en az 2 kat-bazli dict alani uretmeli
    (varyans yuksek, beklenen: doseme_net_scale_by_floor_label + beam_*_floor_scale)."""
    p = kumluca_fit_result.fitted_params
    assert isinstance(p.doseme_net_scale_by_floor_label, dict)
    assert len(p.doseme_net_scale_by_floor_label) >= 3, p.doseme_net_scale_by_floor_label
    assert isinstance(p.beam_formwork_floor_scale, dict)
    assert len(p.beam_formwork_floor_scale) >= 2, p.beam_formwork_floor_scale


def test_fit_field_result_dataclass_round_trip(tmp_path):
    """FitTarget yapilari + dump_fitted_yaml geri yuklenebilir."""
    from metraj.core.structural.calculator import CalcParams
    from metraj.core.structural.config import StructuralConfig
    from metraj.core.structural.profile_fitter import dump_fitted_yaml

    cp = CalcParams(
        column_formwork_strip_fraction=0.42,
        column_concrete_section_fraction=0.48,
        slab_net_area_fraction=0.51,
    )
    out = tmp_path / "fit.yaml"
    dump_fitted_yaml(cp, out, project_name="Test fit")
    assert out.is_file()
    cfg = StructuralConfig.from_file(out)
    assert cfg.params.column_formwork_strip_fraction == pytest.approx(0.42)
    assert cfg.params.column_concrete_section_fraction == pytest.approx(0.48)
    assert cfg.params.slab_net_area_fraction == pytest.approx(0.51)
    # Varsayilan deger korunmus (1.0)
    assert cfg.params.beam_formwork_length_fraction == pytest.approx(1.0)
