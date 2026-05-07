"""DWG'den plan etiketlerini ve x koordinatlarini cikar."""
from __future__ import annotations
import sys
from pathlib import Path
from collections import Counter
import re

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from metraj.core.cad_io import DwgConverter, DxfReader  # noqa: E402

DWG = ROOT / "ornekRef" / "kumluca kaba ataşman na.dwg"


def main():
    converter = DwgConverter()
    dxf = converter.ensure_dxf(DWG)
    model = DxfReader().read(dxf)
    print(f"Toplam text: {len(model.texts)}")

    # Buyuk metinleri al (height > 1.0) — bunlar genelde plan basliklari
    pattern = re.compile(r"(TEMEL|GROBETON|0[.,]00|3[.,]00|6[.,]00|9[.,]00|"
                         r"12[.,]00|15[.,]00|CATI|ÇATI|ASANS|KAT|PLAN)",
                         re.IGNORECASE)
    big_texts = []
    for t in model.texts:
        if not t.text:
            continue
        if not pattern.search(t.text):
            continue
        big_texts.append((t.insert[0], t.insert[1], t.height or 0.0, t.text.strip(), t.layer))

    big_texts.sort(key=lambda x: x[2], reverse=True)
    print(f"\n=== Plan baslik adayi metinler (yuzeysel, n={len(big_texts)}) ===")
    for x, y, h, txt, layer in big_texts[:60]:
        print(f"  x={x:7.1f} y={y:7.1f} h={h:5.2f}  {txt!r:<50}  layer={layer}")


if __name__ == "__main__":
    main()
