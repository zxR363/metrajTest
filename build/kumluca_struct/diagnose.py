"""DWG'deki yapisal polygonlarin gercek dagilimini analiz eder.

Kolon, perde, kiris, doseme polygonlarinin sayisini, perimetre/alan
dagilimini, plan basina dusen miktarini cikarir.  Boylece sapmanin
kaynagini (cift cizim, fazla katman, ekstra polygon) net gormek mumkun.
"""
from __future__ import annotations

import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median, stdev

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from metraj.core.cad_io import DwgConverter, DxfReader  # noqa: E402
from metraj.core.structural import (  # noqa: E402
    detect_structural_layers,
    extract_structural_elements,
)
from metraj.core.structural.floor_segmenter import (  # noqa: E402
    assign_elements_to_plans,
    detect_plan_groups,
)

DWG = ROOT / "ornekRef" / "kumluca kaba ataşman na.dwg"


def main():
    print("== DWG Yapisal Polygon Diyagnozu ==\n")
    converter = DwgConverter()
    dxf = converter.ensure_dxf(DWG)
    model = DxfReader().read(dxf)
    print(f"Total layers: {len(model.layers)}")
    print(f"Total polylines: {len(model.polylines)}")

    layer_report = detect_structural_layers(model.layers)
    elements, _ = extract_structural_elements(model, layer_report=layer_report)

    print(f"\nElement count by kind:")
    by_kind: dict[str, list] = defaultdict(list)
    for el in elements:
        by_kind[el.kind].append(el)
    for k, lst in sorted(by_kind.items(), key=lambda x: -len(x[1])):
        areas = [e.area_m2 for e in lst if e.area_m2 > 0]
        perims = [e.perimeter_m for e in lst if e.perimeter_m > 0]
        print(f"  {k:<20} count={len(lst):>4}  "
              f"avg_area={mean(areas):.3f}m2  med_area={median(areas):.3f}  "
              f"avg_perim={mean(perims):.3f}m  med_perim={median(perims):.3f}")

    from shapely.geometry import Polygon
    # KOLON yakindan inceleme: ortalama, dagilim, "cift cizim" sinyali
    cols = [c for c in by_kind.get("column", []) if isinstance(c.geom, Polygon)]
    if cols:
        print(f"\n=== KOLON detayli (n={len(cols)} polygon) ===")
        # Perim dagilimi histogrami
        perim_buckets = defaultdict(int)
        for c in cols:
            b = round(c.perimeter_m, 1)
            perim_buckets[b] += 1
        top_p = sorted(perim_buckets.items(), key=lambda x: -x[1])[:10]
        print(f"  Perimeter dagilimi (top 10): {top_p}")

        # Buyuk kolonlar (>4m perim) muhtemelen asansor perde / baca
        big = [c for c in cols if c.perimeter_m > 4.0]
        small = [c for c in cols if c.perimeter_m <= 4.0]
        print(f"  Normal kolon (perim<=4m): {len(small)} polygon, "
              f"perim sum={sum(c.perimeter_m for c in small):.1f}m")
        print(f"  Buyuk kolon (perim>4m):   {len(big)} polygon, "
              f"perim sum={sum(c.perimeter_m for c in big):.1f}m")
        for i, c in enumerate(big[:3]):
            xs = [pt[0] for pt in c.geom.exterior.coords]
            ys = [pt[1] for pt in c.geom.exterior.coords]
            print(f"    big[{i}] perim={c.perimeter_m:.2f} area={c.area_m2:.2f} layer={c.layer}")

        # Centroid'lerin yakinlik dagilimi (cift cizimi tespit)
        from shapely.geometry import Point
        centroids = [(c.geom.centroid.x, c.geom.centroid.y) for c in cols]
        # En yakin komsu mesafesi
        nn_dists = []
        for i, (x1, y1) in enumerate(centroids):
            best = float("inf")
            for j, (x2, y2) in enumerate(centroids):
                if i == j:
                    continue
                d = ((x1-x2)**2 + (y1-y2)**2) ** 0.5
                if d < best:
                    best = d
            nn_dists.append(best)
        print(f"  Nearest-neighbor distances:")
        print(f"    min={min(nn_dists):.3f}m, p10={sorted(nn_dists)[len(nn_dists)//10]:.3f}m, "
              f"median={median(nn_dists):.3f}m")
        # Yakindaki cift centroid'leri say
        very_close = sum(1 for d in nn_dists if d < 0.05)
        print(f"  Centroids within 5cm of another: {very_close}")
        close = sum(1 for d in nn_dists if d < 0.5)
        print(f"  Centroids within 50cm of another: {close}")

    # PERDE
    walls = by_kind.get("shear_wall", [])
    if walls:
        print(f"\n=== PERDE detayli (n={len(walls)}) ===")
        for i, w in enumerate(walls[:5]):
            print(f"  [{i}] perim={w.perimeter_m:.2f}m area={w.area_m2:.2f}m2 layer={w.layer}")
        # Layer dagilimi
        layer_count = Counter(w.layer for w in walls)
        print(f"  Layers: {dict(layer_count)}")

    # KIRIS
    beams = by_kind.get("beam", [])
    if beams:
        print(f"\n=== KIRIS detayli (n={len(beams)}) ===")
        for i, b in enumerate(beams[:5]):
            xs = [pt[0] for pt in b.geom.exterior.coords]
            ys = [pt[1] for pt in b.geom.exterior.coords]
            w = max(xs) - min(xs)
            h = max(ys) - min(ys)
            print(f"  [{i}] perim={b.perimeter_m:.2f}m area={b.area_m2:.3f}m2 "
                  f"bbox={w:.2f}x{h:.2f}m aspect={max(w,h)/max(min(w,h),0.001):.1f}")
        # MRR'dan uzun kenarlar
        long_sides = []
        for b in beams:
            try:
                mrr = b.geom.minimum_rotated_rectangle
                coords = list(mrr.exterior.coords)
                if len(coords) >= 4:
                    edges = [
                        ((coords[i+1][0]-coords[i][0])**2 + (coords[i+1][1]-coords[i][1])**2)**0.5
                        for i in range(len(coords)-1)
                    ]
                    edges.sort(reverse=True)
                    long_sides.append(edges[0])
            except Exception:
                continue
        if long_sides:
            print(f"  Beam long-side total: {sum(long_sides):.2f}m  "
                  f"(perim_sum/2 = {sum(b.perimeter_m for b in beams)/2:.2f}m)")
            # GT: 117 + 266*4 + 159 = 1340 m beam length
            print(f"  GT beam length total: ~1340 m")

    # DOSEME plan basina dagilim
    slabs = by_kind.get("slab", [])
    print(f"\n=== DOSEME plan dagilimi (n={len(slabs)}) ===")
    plans = detect_plan_groups(elements, expected_floor_count=7)
    floor_plans, _ = assign_elements_to_plans(
        elements, plans,
        config_floors=[
            {"label": "TEMEL", "elevation_m": -3.0, "storey_height_m": 2.85},
            {"label": "0,00", "elevation_m": 0.0, "storey_height_m": 2.85},
            {"label": "3,00", "elevation_m": 3.0, "storey_height_m": 2.85},
            {"label": "6,00", "elevation_m": 6.0, "storey_height_m": 2.85},
            {"label": "9,00", "elevation_m": 9.0, "storey_height_m": 2.85},
            {"label": "12,00", "elevation_m": 12.0, "storey_height_m": 2.85},
            {"label": "15,00", "elevation_m": 15.0, "storey_height_m": 2.85},
        ],
    )
    print(f"  {'Plan':<10} {'kolon':>6} {'perde':>6} {'kiris':>6} {'doseme':>7} {'minha':>6} "
          f"{'koln_perim':>12} {'doseme_alan':>12}")
    for fp in floor_plans:
        kc = sum(1 for e in fp.elements if e.kind == "column")
        pc = sum(1 for e in fp.elements if e.kind == "shear_wall")
        bc = sum(1 for e in fp.elements if e.kind == "beam")
        sc = sum(1 for e in fp.elements if e.kind == "slab")
        mc = sum(1 for e in fp.elements if e.kind == "slab_opening")
        kperim = sum(e.perimeter_m for e in fp.elements if e.kind == "column")
        salan = sum(e.area_m2 for e in fp.elements if e.kind == "slab")
        print(f"  {fp.label:<10} {kc:>6} {pc:>6} {bc:>6} {sc:>7} {mc:>6} "
              f"{kperim:>10.1f}m {salan:>10.1f}m2")


if __name__ == "__main__":
    main()
