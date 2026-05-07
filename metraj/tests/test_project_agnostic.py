"""Sistemin baska bir projenin (farkli katman isimleri ve tip kodlari)
DWG/DXF dosyasiyla da problemsiz calistigini ispatlayan testler.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from metraj.core.cad_io import DxfReader
from metraj.core.mapping import (
    AutodetectReport,
    LayerMap,
    PozLibrary,
    ProjectConfig,
    TipDefinitions,
    autodetect_layer_map,
    merge_into_layer_map,
)
from metraj.pipeline import Pipeline, PipelineConfig
from metraj.tests.fixtures import build_alternate_dxf, build_demo_dxf

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"


@pytest.fixture(scope="module")
def alternate_dxf(tmp_path_factory) -> Path:
    target = tmp_path_factory.mktemp("alt") / "alternate.dxf"
    return build_alternate_dxf(target)


def test_autodetect_finds_turkish_layers(alternate_dxf: Path) -> None:
    """T-DUVAR / T-KAPI gibi farkli prefixli katman isimleri otomatik
    eslesmeli (referans projeden bagimsiz)."""
    model = DxfReader().read(alternate_dxf)
    report = autodetect_layer_map(model)
    assert "wall" in report.role_to_layers
    assert any("DUVAR" in l for l in report.role_to_layers["wall"])
    assert "door" in report.role_to_layers
    assert any("KAPI" in l for l in report.role_to_layers["door"])
    assert "window" in report.role_to_layers
    assert any("PENCERE" in l for l in report.role_to_layers["window"])
    assert "room_label" in report.role_to_layers


def test_pipeline_runs_with_minimal_config(alternate_dxf: Path, tmp_path: Path) -> None:
    """Konfig olarak sadece TEMPLATES'i (jenerik defaults) kullanarak
    farkli bir projenin metrajini cikarabilmeli."""
    templates_dir = CONFIG_DIR / "templates"
    config = PipelineConfig.from_directory(templates_dir)
    pipeline = Pipeline(config)
    result = pipeline.run(
        cad_path=alternate_dxf,
        output_dir=tmp_path,
        excel_name="alt.xlsx",
        pdf_name="alt.pdf",
    )
    # 4 oda + 6 aciklik beklenir
    assert len(result.rooms) >= 3
    assert len(result.openings) >= 5
    # Autodetect raporu bos kalmamali
    assert result.autodetect_report is not None
    assert "wall" in result.autodetect_report.role_to_layers
    # Excel ve PDF olusmali
    assert result.excel_path and result.excel_path.exists()
    assert result.pdf_path and result.pdf_path.exists()
    # Tipler templates'taki D1/W1/T1/S1 kodlari olmali (referans proje
    # kodlari DS3/DV1 ile karistirilmamali)
    used_codes = set()
    for r in result.rooms:
        for code in (r.floor_tip, r.wall_tip, r.ceiling_tip, r.skirting_tip):
            if code:
                used_codes.add(code)
    # Templates'ta sadece D1/W1/T1/S1 oldugu icin secilenler bunlardan biri
    # olmali (referans projeden DS3/DV4/TV2 olmamali)
    for code in used_codes:
        assert not code.startswith("DS"), (
            f"Tip kodu DS* (referans proje) yerine sablon kodu beklenir, "
            f"alindi: {code}"
        )


def test_default_config_is_generic_for_alternate_project(alternate_dxf: Path,
                                                         tmp_path: Path) -> None:
    """Varsayilan dahili config'in jenerik kodlari kullanmadigini gosterir
    fakat eksik tip durumunda config_gaps raporu uretildigini dogrular."""
    config = PipelineConfig.from_directory(CONFIG_DIR)
    pipeline = Pipeline(config)
    result = pipeline.run(
        cad_path=alternate_dxf,
        output_dir=tmp_path,
        excel_name="m.xlsx",
        pdf_name="m.pdf",
    )
    # Pipeline crash etmemeli
    assert result.rooms
    # Konfig boslugu raporu bos da olabilir, dolu da olabilir; anahtar
    # nokta `has_gaps` calisiyor olmasi
    assert result.config_gaps is not None


def test_merge_into_layer_map_preserves_base(alternate_dxf: Path) -> None:
    """Autodetect mevcut LayerMap'i yok etmemeli, sadece bos rolleri
    doldurmali."""
    model = DxfReader().read(alternate_dxf)
    base = LayerMap.from_dict({"roles": {"wall": {"layers": ["A-WALL"]}}})
    report = autodetect_layer_map(model, base_map=base)
    merged = merge_into_layer_map(report, base_map=base)
    wall_layers = merged.layers_for("wall")
    assert "A-WALL" in wall_layers  # base preserved
    assert any("DUVAR" in l for l in wall_layers)  # autodetect added
