"""Hangi katmanlardaki polygonlar hangi yapisal kind'a atanmis incele."""
from __future__ import annotations
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from metraj.core.cad_io import DwgConverter, DxfReader  # noqa: E402
from metraj.core.structural import detect_structural_layers, extract_structural_elements  # noqa: E402

DWG = ROOT / "ornekRef" / "kumluca kaba ataşman na.dwg"


def main():
    converter = DwgConverter()
    dxf = converter.ensure_dxf(DWG)
    model = DxfReader().read(dxf)

    layer_report = detect_structural_layers(model.layers)
    print("=== Katman -> Kind atamasi ===")
    by_kind = defaultdict(list)
    for layer, kind in layer_report.layer_to_kind.items():
        by_kind[kind].append(layer)
    for kind, layers in sorted(by_kind.items()):
        print(f"\n  {kind}:")
        for l in sorted(layers):
            count = sum(1 for p in model.polylines if p.layer == l and p.closed)
            count_open = sum(1 for p in model.polylines if p.layer == l and not p.closed)
            count_hatch = sum(1 for h in model.hatches if h.layer == l)
            if count + count_hatch > 0:
                print(f"    {l!r:<60} closed_poly={count:>4}  open={count_open:>4}  hatch={count_hatch}")

    # Her elementi hangi katmanli polygon yarattigini izle
    elements, _ = extract_structural_elements(model, layer_report=layer_report)
    print(f"\n=== Element kind dagilimi (extract sonrasi) ===")
    el_by_kind = defaultdict(list)
    for el in elements:
        el_by_kind[el.kind].append(el)
    for kind, lst in sorted(el_by_kind.items(), key=lambda x: -len(x[1])):
        layers = Counter(e.layer for e in lst)
        print(f"\n  {kind} ({len(lst)} polygon):")
        for l, c in layers.most_common(10):
            print(f"    {l!r:<60} {c} polygon")


if __name__ == "__main__":
    main()
