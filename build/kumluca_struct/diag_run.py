"""Pipeline'i calistirip plan basina ne atanmis raporla."""
from __future__ import annotations
import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from metraj.core.structural import StructuralPipeline, default_config  # noqa: E402

DWG = ROOT / "ornekRef" / "kumluca kaba ataşman na.dwg"


def main():
    cfg = default_config()
    cfg.expected_floor_count = 7
    cfg.params.foundation_depth_m = 0.5
    cfg.params.lean_concrete_thickness_m = 0.10
    cfg.params.slab_thickness_m = 0.15
    cfg.params.typical_storey_height_m = 3.0  # kumluca 3.00 m
    pipe = StructuralPipeline(cfg)
    res = pipe.run(DWG, output_dir=ROOT / "build/kumluca_struct/out", write_excel=False)
    print(f"\nPlan kumesi: {res.plan_count}")
    print(f"\n{'Label':<14} {'Mult':>5} {'Extra':<25} {'kolon':>5} {'perde':>5} "
          f"{'kiris':>5} {'doseme':>6} {'minha':>5}")
    for fp in res.smodel.floors:
        kc = sum(1 for e in fp.elements if e.kind == "column")
        pc = sum(1 for e in fp.elements if e.kind == "shear_wall")
        bc = sum(1 for e in fp.elements if e.kind == "beam")
        sc = sum(1 for e in fp.elements if e.kind == "slab")
        mc = sum(1 for e in fp.elements if e.kind == "slab_opening")
        ex = ",".join(fp.extra_labels) if fp.extra_labels else "-"
        print(f"  {fp.label:<12} {fp.multiplier:>5} {ex:<25} "
              f"{kc:>5} {pc:>5} {bc:>5} {sc:>6} {mc:>5}")


if __name__ == "__main__":
    main()
