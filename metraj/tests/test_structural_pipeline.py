"""Yapisal pipeline uctan uca smoke testi (Faz 0 baz cizgi).

Kumluca DXF + kumluca.yaml profil ile pipeline'i calistirir ve referans Excel
karsi sapma rakamlarini dogrular:

    KALIP max rel sapma ≤ %1
    BETON max rel sapma ≤ %1

Onceki kosumda gozlenen baz cizgi (build_compare_kumluca_gt/dogrulama_ozeti.txt):
    KALIP %0.4759, BETON %0.8705, 27 uyari satiri.

Bu test gelecek fazlarda (Faz 1+ degisikliklerde) regression koruma noktasidir.
Gercek Kumluca DXF/DWG dosyasi proje kokunde yoksa testler ``skip`` edilir.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CAD_CANDIDATES = [
    ROOT / "ornekRef" / "kumluca kaba ataşman na.dxf",
    ROOT / "ornekRef" / "kumluca kaba ataşman na.dwg",
]
KUMLUCA_YAML = ROOT / "metraj" / "config" / "references" / "kumluca.yaml"


def _resolve_cad() -> Path | None:
    for p in CAD_CANDIDATES:
        if p.is_file():
            return p
    return None


def _kumluca_yaml() -> Path | None:
    return KUMLUCA_YAML if KUMLUCA_YAML.is_file() else None


@pytest.mark.slow
def test_kumluca_pipeline_runs_under_one_percent(kumluca_paths, tmp_path):
    """Kumluca DXF + kumluca.yaml: KALIP ve BETON sapma esigi %1 altinda olmali.

    Bu test diagnostics JSON yazimini da dogrular; bu nedenle paylasilan
    `kumluca_pipeline_result` fixture'ini kullanamiyor (o write_diagnostics=False).
    """
    if kumluca_paths is None:
        pytest.skip("Kumluca girdileri yok")
    cad, _ref, yaml_p = kumluca_paths

    from metraj.core.structural.config import StructuralConfig
    from metraj.core.structural.pipeline import StructuralPipeline

    cfg = StructuralConfig.from_file(yaml_p)
    pipe = StructuralPipeline(config=cfg)
    res = pipe.run(cad_path=cad, output_dir=tmp_path, write_excel=False)

    assert res.validation_detail is not None, \
        "compare_to_reference acik olmali; validation_detail bos donmemeli"

    max_k = res.validation_detail.max_rel_error_formwork
    max_b = res.validation_detail.max_rel_error_concrete

    # Baz cizgi (Faz 0): KALIP %0.4759, BETON %0.8705 — %1 esigi altinda.
    assert max_k <= 0.01, (
        f"KALIP regression: {max_k*100:.4f}% > %1 esik "
        f"(baz cizgi ~%0.48)"
    )
    assert max_b <= 0.01, (
        f"BETON regression: {max_b*100:.4f}% > %1 esik "
        f"(baz cizgi ~%0.87)"
    )

    # Faz 0 diagnostics JSON yazilmali (gelecek fazlar bunu girdi alacak).
    assert res.diagnostics_path is not None and res.diagnostics_path.is_file()
    payload = json.loads(res.diagnostics_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["element_total"] > 0
    assert isinstance(payload["floors"], list) and len(payload["floors"]) > 0
    assert "summary_by_kind" in payload


def test_diagnostics_module_handles_empty_model():
    """Diagnostics modulu bos model'de patlamaz; minimal serilestirme yapar."""
    from metraj.core.structural.diagnostics import diagnose_model, write_diagnostics_json
    from metraj.core.structural.elements import StructuralModel

    payload = diagnose_model(StructuralModel())
    assert payload["floor_count"] == 0
    assert payload["element_total"] == 0
    assert payload["floors"] == []
    assert payload["unassigned"] == []


def test_diagnostics_module_serializes_synthetic_element(tmp_path):
    """Sentetik bir kolon elemani: bbox, aspect_ratio, area dogru hesaplanir."""
    from shapely.geometry import Polygon

    from metraj.core.structural.diagnostics import (
        diagnose_element,
        write_diagnostics_json,
    )
    from metraj.core.structural.elements import (
        FloorPlan,
        StructuralElement,
        StructuralModel,
    )

    # 0.7 x 0.5 m kolon
    poly = Polygon([(0, 0), (0.7, 0), (0.7, 0.5), (0, 0.5)])
    el = StructuralElement(
        kind="column", layer="KOLON NA", geom=poly,
        area_m2=poly.area, perimeter_m=poly.length, length_m=0.0,
        floor_label="0,00",
    )
    d = diagnose_element(el)
    assert d.kind == "column"
    assert d.geom_type == "Polygon"
    assert d.area_m2 == pytest.approx(0.35)
    assert d.aspect_ratio == pytest.approx(0.7 / 0.5)
    assert d.bbox == pytest.approx((0.0, 0.0, 0.7, 0.5))

    fp = FloorPlan(label="0,00", index=1, elevation_m=0.0,
                   storey_height_m=2.85, bbox=(0, 0, 10, 10), elements=[el])
    smodel = StructuralModel(floors=[fp])

    out = write_diagnostics_json(smodel, tmp_path / "diag.json")
    assert out.is_file()
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["element_total"] == 1
    assert payload["summary_by_kind"] == {"column": 1}
    assert payload["floors"][0]["elements"][0]["kind"] == "column"


def test_strip_kot_prefix_labels_from_yaml_matches_default():
    """kumluca.yaml strip_kot_prefix_labels listesi gt_io.py default'u ile ayni
    sonuc uretmeli — gerileme kontrol noktasi (alias migrasyonu)."""
    from metraj.core.structural.config import StructuralConfig
    from metraj.core.structural.gt_io import (
        KUMLUCA_STRIP_KOT_PREFIX_REST,
        comparison_key,
        merge_comparison_aliases,
    )

    yaml_p = _kumluca_yaml()
    if yaml_p is None:
        pytest.skip("kumluca.yaml bulunamadi")
    cfg = StructuralConfig.from_file(yaml_p)
    # YAML listesi default ile ayni icerige sahip olmali
    assert frozenset(cfg.strip_kot_prefix_labels) == KUMLUCA_STRIP_KOT_PREFIX_REST

    # Bir YAML-override sentetik testi: liste degisirse comparison_key davranisi
    # da degisir.
    aliases = merge_comparison_aliases("kumluca", cfg.comparison_label_aliases)
    # Default davranis: "+2,85 DOSEME YAN" -> "DOSEME YAN" (default ile)
    k_default = comparison_key("+2,85 DOSEME YAN", aliases, excel_layout="kumluca")
    assert k_default == "DOSEME YAN"
    # Empty strip set ile aynı etiket kirpilmaz: "+2,85 DOSEME YAN" -> "3,00 DOSEME YAN"
    # (kot alias 2,85 -> 3,00 hala uygulanir)
    k_empty_strip = comparison_key(
        "+2,85 DOSEME YAN", aliases, excel_layout="kumluca",
        strip_prefix_labels=frozenset(),
    )
    assert k_empty_strip != "DOSEME YAN"
