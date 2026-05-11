"""Excel-bagimsiz config dialog: non-GUI helper testleri."""
from __future__ import annotations

from pathlib import Path

import pytest

from metraj.app.structural_config_dialog import (
    FIELD_GROUPS,
    calcparams_to_yaml,
    field_groups_to_flat_list,
    list_method_presets,
    load_method_preset,
)
from metraj.core.structural.calculator import CalcParams


def test_method_presets_are_discoverable():
    presets = list_method_presets()
    assert "geometry_full" in presets
    assert "geometry_half" in presets
    assert "custom_template" in presets


def test_load_geometry_full_all_ones():
    cp = load_method_preset("geometry_full")
    assert cp.column_formwork_strip_fraction == pytest.approx(1.0)
    assert cp.column_concrete_section_fraction == pytest.approx(1.0)
    assert cp.shear_wall_concrete_section_fraction == pytest.approx(1.0)
    assert cp.beam_formwork_length_fraction == pytest.approx(1.0)
    assert cp.slab_net_area_fraction == pytest.approx(1.0)
    assert cp.foundation_plan_formwork_scale == pytest.approx(1.0)
    assert cp.elevator_shaft_quantity_scale == pytest.approx(1.0)


def test_load_geometry_half_kumluca_style():
    cp = load_method_preset("geometry_half")
    assert cp.column_formwork_strip_fraction == pytest.approx(0.5)
    assert cp.column_concrete_section_fraction == pytest.approx(0.5)
    assert cp.slab_net_area_fraction == pytest.approx(0.5)
    assert cp.foundation_concrete_section_fraction == pytest.approx(0.5)
    assert cp.elevator_shaft_quantity_scale == pytest.approx(1.0 / 3.0)


def test_load_missing_preset_raises():
    with pytest.raises(FileNotFoundError):
        load_method_preset("nonexistent_preset_xyz")


def test_calcparams_to_yaml_writes_excel_independent_yaml(tmp_path):
    """YAML compare_to_reference=False + excel_layout=generic olmali."""
    cp = CalcParams(
        column_formwork_strip_fraction=0.45,
        slab_net_area_fraction=0.5,
        beam_depth_m=0.50,
    )
    out = tmp_path / "p.yaml"
    calcparams_to_yaml(cp, out, project_name="Test")
    text = out.read_text(encoding="utf-8")
    assert "compare_to_reference: false" in text
    assert "excel_layout: generic" in text

    # StructuralConfig ile yuklenebilir mi
    from metraj.core.structural.config import StructuralConfig
    cfg = StructuralConfig.from_file(out)
    assert cfg.compare_to_reference is False
    assert cfg.excel_layout == "generic"
    assert cfg.params.column_formwork_strip_fraction == pytest.approx(0.45)
    assert cfg.params.slab_net_area_fraction == pytest.approx(0.5)
    assert cfg.params.beam_depth_m == pytest.approx(0.50)


def test_field_groups_cover_critical_calcparams_fields():
    """FIELD_GROUPS yapilandirma alanlari CalcParams'da gercekten mevcut olmali."""
    flat = field_groups_to_flat_list()
    cp = CalcParams()
    for fdef in flat:
        assert hasattr(cp, fdef.name), f"FieldDef.name CalcParams'da yok: {fdef.name}"


def test_field_groups_include_main_categories():
    """En az 5 grup: Kolon, Perde, Kiris, Doseme, Temel + Minha + Cati."""
    keys = list(FIELD_GROUPS.keys())
    assert len(keys) >= 7  # Minha + Cati eklendi
    # Anahtar kelimeler en az bir grupta gecmeli
    s = " ".join(keys).upper()
    for kw in ("KOLON", "PERDE", "KIRIS", "DOSEME", "MINHA", "CATI"):
        assert kw in s, f"Grup eksik: {kw}"


def test_minha_fields_in_dialog():
    """Minha (eksiltme) alanlari UI'da yer almali."""
    flat = field_groups_to_flat_list()
    names = {f.name for f in flat}
    for required in (
        "slab_opening_concrete_scale",
        "kolon_head_minha_scale",
        "beam_join_minha_m",
        "beam_zemin_concrete_qty_scale",
    ):
        assert required in names, f"UI'da eksik minha alani: {required}"


def test_advanced_dimension_fields_in_dialog():
    """Ileri boyut alanlari (cati, asansor, baca) UI'da olmali."""
    flat = field_groups_to_flat_list()
    names = {f.name for f in flat}
    for required in (
        "beam_height_m",
        "roof_slab_thickness_m",
        "roof_protection_thickness_m",
        "elevator_extra_height_m",
        "chimney_height_m",
    ):
        assert required in names, f"UI'da eksik ileri boyut alani: {required}"


def test_geometry_full_preset_minha_fields():
    """geometry_full preset minha alanlarini 1.0 olarak set etmeli."""
    cp = load_method_preset("geometry_full")
    assert cp.slab_opening_concrete_scale == pytest.approx(1.0)
    assert cp.kolon_head_minha_scale == pytest.approx(1.0)
    assert cp.beam_zemin_concrete_qty_scale == pytest.approx(1.0)


def test_geometry_half_preset_minha_fields():
    """geometry_half preset Kumluca-stili minha degerlerini icermeli."""
    cp = load_method_preset("geometry_half")
    assert cp.slab_opening_concrete_scale == pytest.approx(0.906)
    assert cp.kolon_head_minha_scale == pytest.approx(0.807)
    assert cp.beam_zemin_concrete_qty_scale == pytest.approx(0.434)


def test_calcparams_to_yaml_includes_layer_overrides(tmp_path):
    """structural_layer_include_kind ve structural_layer_exclude YAML'a yazilmali."""
    cp = CalcParams()
    out = tmp_path / "with_overrides.yaml"
    calcparams_to_yaml(
        cp, out,
        structural_layer_include_kind={"K-30x60": "column", "P-A": "shear_wall"},
        structural_layer_exclude=["IZ_KOLON_PRY"],
    )
    text = out.read_text(encoding="utf-8")
    assert "structural_layer_include_kind" in text
    assert "K-30x60" in text
    assert "structural_layer_exclude" in text

    from metraj.core.structural.config import StructuralConfig
    cfg = StructuralConfig.from_file(out)
    assert cfg.structural_layer_include_kind == {"K-30x60": "column", "P-A": "shear_wall"}
    assert cfg.structural_layer_exclude == ["IZ_KOLON_PRY"]


def test_calcparams_to_yaml_includes_dict_fields(tmp_path):
    """Kat-bazli dict alanlari (doseme_net_scale_by_floor_label vb.) YAML'a yazilmali."""
    cp = CalcParams(
        slab_net_area_fraction=0.5,
        doseme_net_scale_by_floor_label={"0,00": 1.04, "+2,85": 1.05},
        beam_formwork_floor_scale={"+11,40": 1.69},
    )
    out = tmp_path / "dict_fields.yaml"
    calcparams_to_yaml(cp, out)

    from metraj.core.structural.config import StructuralConfig
    cfg = StructuralConfig.from_file(out)
    assert cfg.params.doseme_net_scale_by_floor_label == {"0,00": 1.04, "+2,85": 1.05}
    assert cfg.params.beam_formwork_floor_scale == {"+11,40": 1.69}


def test_preset_dump_round_trip_via_yaml(tmp_path):
    """Preset yukle -> YAML kaydet -> tekrar yukle: ayni CalcParams."""
    cp_a = load_method_preset("geometry_half")
    out = tmp_path / "rt.yaml"
    calcparams_to_yaml(cp_a, out)
    from metraj.core.structural.config import StructuralConfig
    cfg = StructuralConfig.from_file(out)
    assert cfg.params.column_formwork_strip_fraction == pytest.approx(0.5)
    assert cfg.params.elevator_shaft_quantity_scale == pytest.approx(1.0 / 3.0)


def test_cli_config_wizard_preset_only_mode(tmp_path):
    """`metraj config-wizard --preset-only` GUI olmadan YAML uretebilmeli."""
    import subprocess
    out = tmp_path / "preset.yaml"
    result = subprocess.run(
        [
            "/Library/Frameworks/Python.framework/Versions/3.14/bin/python3.14",
            "-m", "metraj.cli", "config-wizard",
            "--preset", "geometry_full",
            "--preset-only",
            "-o", str(out),
        ],
        capture_output=True, text=True, cwd=str(Path(__file__).resolve().parents[2]),
    )
    assert result.returncode == 0, result.stderr
    assert out.is_file()
    assert "geometry_full" in result.stdout or out.read_text().count("compare_to_reference: false") == 1


def test_cli_config_wizard_list_presets():
    """`metraj config-wizard --list-presets` mevcut presetleri stdout'a yazmali."""
    import subprocess
    result = subprocess.run(
        [
            "/Library/Frameworks/Python.framework/Versions/3.14/bin/python3.14",
            "-m", "metraj.cli", "config-wizard",
            "--list-presets",
        ],
        capture_output=True, text=True, cwd=str(Path(__file__).resolve().parents[2]),
    )
    assert result.returncode == 0, result.stderr
    assert "geometry_full" in result.stdout
    assert "geometry_half" in result.stdout
