"""Pytest fixture'lari: pahali pipeline kosumlarini session-scope cache eder.

Slow testler (Kumluca DXF + pipeline + profile_fitter) tek seferlik bir
DXF parse'i (~8sn) yapar; bu module 3+ slow test arasinda paylasarak
toplam suresi onemli olcude azaltir.

Kullanim:

.. code-block:: python

   @pytest.mark.slow
   def test_kumluca_pipeline(kumluca_pipeline_result):
       assert kumluca_pipeline_result.validation_detail is not None
"""
from __future__ import annotations

from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
_KUMLUCA_CAD_CANDIDATES = [
    ROOT / "ornekRef" / "kumluca kaba ataşman na.dxf",
    ROOT / "ornekRef" / "kumluca kaba ataşman na.dwg",
]
_KUMLUCA_EXCEL = ROOT / "ornekRef" / "kumluca kaba.xlsx"
_KUMLUCA_YAML = ROOT / "metraj" / "config" / "references" / "kumluca.yaml"


def _resolve_kumluca_cad() -> Path | None:
    for p in _KUMLUCA_CAD_CANDIDATES:
        if p.is_file():
            return p
    return None


@pytest.fixture(scope="session")
def kumluca_paths() -> tuple[Path, Path, Path] | None:
    """(cad, reference_excel, kumluca_yaml) uclüsü; biri eksikse None."""
    cad = _resolve_kumluca_cad()
    if cad is None or not _KUMLUCA_EXCEL.is_file() or not _KUMLUCA_YAML.is_file():
        return None
    return (cad, _KUMLUCA_EXCEL, _KUMLUCA_YAML)


@pytest.fixture(scope="session")
def kumluca_pipeline_result(kumluca_paths, tmp_path_factory):
    """Kumluca pipeline ciktisi (kalibre profil ile); session boyunca cache.

    Birden fazla slow test ayni sonucu kullanabilir; tek kosumdan paylasilir.
    """
    if kumluca_paths is None:
        pytest.skip("Kumluca girdileri yok")
    cad, _ref, yaml_p = kumluca_paths
    from metraj.core.structural.config import StructuralConfig
    from metraj.core.structural.pipeline import StructuralPipeline

    cfg = StructuralConfig.from_file(yaml_p)
    pipe = StructuralPipeline(config=cfg)
    out_dir = tmp_path_factory.mktemp("kumluca_run")
    return pipe.run(cad_path=cad, output_dir=out_dir,
                    write_excel=False, write_diagnostics=False)


@pytest.fixture(scope="session")
def kumluca_fit_result(kumluca_paths, tmp_path_factory):
    """Profile fitter ciktisi (Faz 4 v2 iki-asamali); session cache.

    `test_profile_fitter` icinde paylasilir; her test kendi pipeline'ini
    cikarmak yerine bu fixture'i kullanir.
    """
    if kumluca_paths is None:
        pytest.skip("Kumluca girdileri yok")
    cad, ref, _yaml = kumluca_paths
    from metraj.core.structural.profile_fitter import fit_profile_from_dxf
    out = tmp_path_factory.mktemp("kumluca_fit") / "fitted.yaml"
    return fit_profile_from_dxf(
        cad_path=cad, reference_excel=ref,
        output_yaml=out, two_stage_fit=True,
    )
