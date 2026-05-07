"""Yapisal (kaba insaat) metraj modulu.

Ana akış: DWG/DXF çiziminden kapalı poligonlar ve kat planları ile kalıp m² /
beton m³ hesabı; çıktı Excel düzeni ``excel_layout: kumluca`` ile örnek
dosya ile uyumlu olabilir.

İsteğe bağlı: ``reference_excel_path`` ile ground truth karşılaştırması
(``compare_to_reference``). Çıktı rakamları her zaman DWG hesabıdır; referans
Excel yalnızca sapma ölçümü içindir.
"""
from .calculator import CalcParams, CalcRow, StructuralReport, calculate  # noqa: F401
from .config import StructuralConfig, default_config  # noqa: F401
from .elements import (  # noqa: F401
    ElementKind,
    FloorPlan,
    StructuralElement,
    StructuralModel,
)
from .excel_writer import write_structural_xlsx  # noqa: F401
from .extractor import deduplicate, extract_structural_elements  # noqa: F401
from .floor_segmenter import (  # noqa: F401
    assign_elements_to_plans,
    attach_floor_labels,
    detect_plan_groups,
)
from .layer_detection import detect_structural_layers  # noqa: F401
from .pipeline import (  # noqa: F401
    StructuralPipeline,
    StructuralPipelineResult,
    ValidationCompareSummary,
    detect_drawing_kind,
)

__all__ = [
    "CalcParams",
    "CalcRow",
    "StructuralConfig",
    "StructuralElement",
    "StructuralModel",
    "StructuralPipeline",
    "StructuralPipelineResult",
    "StructuralReport",
    "ValidationCompareSummary",
    "FloorPlan",
    "ElementKind",
    "default_config",
    "calculate",
    "extract_structural_elements",
    "deduplicate",
    "detect_structural_layers",
    "detect_plan_groups",
    "attach_floor_labels",
    "assign_elements_to_plans",
    "write_structural_xlsx",
    "detect_drawing_kind",
]
