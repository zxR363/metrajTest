"""Plan segmentation kontrolu: kac DWG plan kumesi var, X koordinatlari nasil?"""
from __future__ import annotations
import sys
from pathlib import Path
from collections import Counter

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from metraj.core.cad_io import DwgConverter, DxfReader  # noqa: E402
from metraj.core.structural import (  # noqa: E402
    detect_structural_layers,
    extract_structural_elements,
)
from metraj.core.structural.extractor import hash_dedupe_by_geometry  # noqa: E402
from metraj.core.structural.classify import remove_collinear_centroids  # noqa: E402
from metraj.core.structural.floor_segmenter import detect_plan_groups  # noqa: E402

DWG = ROOT / "ornekRef" / "kumluca kaba ataşman na.dwg"


def main():
    converter = DwgConverter()
    dxf = converter.ensure_dxf(DWG)
    model = DxfReader().read(dxf)
    layer_report = detect_structural_layers(model.layers)
    elements, _ = extract_structural_elements(model, layer_report=layer_report)
    print(f"Ham eleman: {len(elements)}")
    elements = hash_dedupe_by_geometry(elements)
    elements = remove_collinear_centroids(elements, tol_m=0.05)
    print(f"Dedupe sonrasi: {len(elements)}")

    # 2B histogram: X ve Y koordinatlari
    pts = []
    for e in elements:
        try:
            c = e.geom.centroid
            pts.append((c.x, c.y))
        except Exception:
            pass
    if not pts:
        return
    xs = sorted(p[0] for p in pts)
    ys = sorted(p[1] for p in pts)
    print(f"\nY range: {ys[0]:.1f} - {ys[-1]:.1f}, median: {ys[len(ys)//2]:.1f}")
    # Y histogram
    span_y = ys[-1] - ys[0]
    bin_w_y = span_y / 12.0 if span_y > 0 else 1.0
    bins_y = Counter()
    for _, y in pts:
        b = int((y - ys[0]) / bin_w_y) if bin_w_y > 0 else 0
        bins_y[b] += 1
    print("Y histogram:")
    for b in sorted(bins_y):
        y_start = ys[0] + b * bin_w_y
        print(f"  bin[{b:>2}] y={y_start:7.1f}: {'#' * (bins_y[b] // 5)}{bins_y[b]}")
    print(f"\nX koordinati range: {xs[0]:.1f} - {xs[-1]:.1f}")
    print(f"X median: {xs[len(xs)//2]:.1f}")
    print(f"X p10: {xs[len(xs)//10]:.1f}, p25: {xs[len(xs)//4]:.1f}, "
          f"p75: {xs[3*len(xs)//4]:.1f}, p90: {xs[9*len(xs)//10]:.1f}")
    # Histogram (10 bin)
    span = xs[-1] - xs[0]
    bin_w = span / 14.0  # ~14 bin (7 plan x 2 araligi)
    bins = Counter()
    for x in xs:
        b = int((x - xs[0]) / bin_w)
        bins[b] += 1
    for b in sorted(bins):
        x_start = xs[0] + b * bin_w
        print(f"  bin[{b:>2}] x={x_start:7.1f}: {'#' * (bins[b] // 5)}{bins[b]}")

    # Plan grouping
    print(f"\n--- expected_floor_count=7 (zorlama) ---")
    plans7 = detect_plan_groups(elements, expected_floor_count=7)
    for i, p in enumerate(plans7):
        xmin, _, xmax, _ = p.bbox
        print(f"  plan[{i}]: x=[{xmin:.1f}, {xmax:.1f}] genislik={xmax-xmin:.1f}m  label={p.label}")

    print(f"\n--- expected_floor_count=None (otomatik) ---")
    plans_auto = detect_plan_groups(elements)
    print(f"detect_plan_groups -> {len(plans_auto)} plan")
    for i, p in enumerate(plans_auto):
        xmin, _, xmax, _ = p.bbox
        print(f"  plan[{i}]: x=[{xmin:.1f}, {xmax:.1f}] genislik={xmax-xmin:.1f}m")


if __name__ == "__main__":
    main()
