"""Faz 0 PoC dogrulama scripti.

Mevcut Excel mahal kitabini parse edip 'altin standart' istatistik raporu
uretir.  DWG cikarimi yapildiktan sonra bu rapor otomasyon ciktisi ile
karsilastirilir (`metraj.cli compare`).

Kullanim:
    python -m metraj.scripts.poc_groundtruth /path/to/Mahal.xlsx
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

from ..core.excel.ground_truth import GroundTruthReader


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    if not argv:
        print("Kullanim: python -m metraj.scripts.poc_groundtruth <excel>")
        return 2
    excel_path = Path(argv[0])
    if not excel_path.exists():
        print(f"Dosya bulunamadi: {excel_path}")
        return 1

    book = GroundTruthReader().read(excel_path)
    rooms = book.rooms
    print(f"=== Ground-truth raporu: {excel_path.name} ===")
    print(f"Mahal sayisi          : {len(rooms)}")
    if not rooms:
        return 0
    floors = Counter(r.floor for r in rooms)
    print(f"Kat dagilimi          : {dict(floors)}")
    floor_tip = Counter(r.floor_tip for r in rooms if r.floor_tip)
    wall_tip = Counter(r.wall_tip for r in rooms if r.wall_tip)
    ceiling_tip = Counter(r.ceiling_tip for r in rooms if r.ceiling_tip)
    print(f"Doseme tipleri        : {dict(floor_tip.most_common())}")
    print(f"Duvar tipleri         : {dict(wall_tip.most_common())}")
    print(f"Tavan tipleri         : {dict(ceiling_tip.most_common())}")
    total_area = sum(r.area for r in rooms)
    total_perimeter = sum(r.perimeter for r in rooms)
    print(f"Toplam alan (m2)      : {total_area:,.2f}")
    print(f"Toplam cevre (m)      : {total_perimeter:,.2f}")
    print(f"Ort. yukseklik (m)    : {sum(r.height for r in rooms) / len(rooms):.2f}")
    minha_floor = sum(r.floor_minha for r in rooms)
    minha_wall = sum(r.wall_minha for r in rooms)
    minha_skirting = sum(r.skirting_minha for r in rooms)
    print(f"Toplam doseme minha   : {minha_floor:,.2f}")
    print(f"Toplam duvar minha    : {minha_wall:,.2f}")
    print(f"Toplam supurgelik mn  : {minha_skirting:,.2f}")

    if book.totals_by_kategori:
        print()
        print("Icmal kategori toplamlari:")
        for kategori, miktar in sorted(book.totals_by_kategori.items()):
            print(f"  {kategori:<30s} {miktar:>14,.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
