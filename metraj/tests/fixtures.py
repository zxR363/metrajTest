"""Synthetic DXF fixture generators for tests and demos.

When the firma's DWG cannot be opened (because ODA File Converter is not
installed), these fixtures provide a deterministic 5-room scene that the
pipeline can chew on end-to-end.
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Sequence, Tuple

import ezdxf

Point = Tuple[float, float]


def _add_room(msp, layer_walls: str, layer_label: str,
              x: float, y: float, w: float, h: float,
              code: str, name: str, label_layer_role: str = "A-AREA-IDEN") -> None:
    pts = [(x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y)]
    for a, b in zip(pts, pts[1:]):
        msp.add_line(a, b, dxfattribs={"layer": layer_walls})
    # MTEXT preserves multi-line content; single-line TEXT collapses the newline.
    cx = x + w / 2
    cy = y + h / 2
    msp.add_mtext(
        f"{code}\\P{name}",
        dxfattribs={"layer": label_layer_role, "char_height": 0.3,
                    "insert": (cx, cy, 0)},
    )


def _add_door(msp, x: float, y: float, width: float = 1.0, height: float = 2.4,
              layer: str = "A-DOOR") -> None:
    msp.add_blockref(
        "KAPI_100x240",
        insert=(x, y),
        dxfattribs={"layer": layer},
    )


def _add_window(msp, x: float, y: float, width: float = 1.5, height: float = 1.5,
                layer: str = "A-GLAZ") -> None:
    msp.add_blockref(
        "PENCERE_150x150",
        insert=(x, y),
        dxfattribs={"layer": layer},
    )


def build_demo_dxf(out_path: str | Path) -> Path:
    """Five-room office floor in a single DXF file.

    Layout:
        +----------+----------+----------+
        |  KORIDOR (12 x 4)             |
        +----------+----------+----------+
        |  OFIS    |  WC      |  DEPO    |
        |  4x5     |  3x5     |  4x5     |
        +----------+----------+----------+

    """
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    doc = ezdxf.new(setup=True, dxfversion="R2018")
    doc.header["$INSUNITS"] = 6  # meters

    for layer_name in ("A-WALL", "A-DOOR", "A-GLAZ", "A-AREA-IDEN"):
        if layer_name not in doc.layers:
            doc.layers.add(layer_name)

    # Block definitions for openings
    if "KAPI_100x240" not in doc.blocks:
        kapi = doc.blocks.new(name="KAPI_100x240")
        kapi.add_line((-0.5, 0), (0.5, 0))
    if "PENCERE_150x150" not in doc.blocks:
        pencere = doc.blocks.new(name="PENCERE_150x150")
        pencere.add_line((-0.75, 0), (0.75, 0))
        pencere.add_line((-0.75, 0.05), (0.75, 0.05))

    msp = doc.modelspace()

    # KORIDOR
    _add_room(msp, "A-WALL", "A-AREA-IDEN", 0, 5, 12, 4, "Z-01", "KORIDOR")
    # OFIS
    _add_room(msp, "A-WALL", "A-AREA-IDEN", 0, 0, 4, 5, "Z-02", "OFIS")
    # WC
    _add_room(msp, "A-WALL", "A-AREA-IDEN", 4, 0, 3, 5, "Z-03", "WC")
    # DEPO
    _add_room(msp, "A-WALL", "A-AREA-IDEN", 7, 0, 4, 5, "Z-04", "DEPO")
    # SALON (right wing)
    _add_room(msp, "A-WALL", "A-AREA-IDEN", 12, 0, 6, 9, "Z-05", "SALON")

    # Doors (one per non-corridor room, opening into the corridor)
    _add_door(msp, 2, 5)  # OFIS -> KORIDOR
    _add_door(msp, 5.5, 5)
    _add_door(msp, 9, 5)
    _add_door(msp, 12, 7)  # SALON
    # Windows on the perimeter
    _add_window(msp, 2, 0)
    _add_window(msp, 9, 0)
    _add_window(msp, 15, 0)

    doc.saveas(out)
    return out


def build_alternate_dxf(out_path: str | Path) -> Path:
    """Different layer naming convention + room codes than the reference project.

    Used to prove the pipeline is project-agnostic: it must auto-detect
    layers like ``T-DUVAR`` (Turkish "T-" prefix) and ``T-KAPI`` and assign
    tipler from a custom code set.
    """
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    doc = ezdxf.new(setup=True, dxfversion="R2018")
    doc.header["$INSUNITS"] = 6  # meters

    # Different layer names: T-DUVAR, T-KAPI, T-PENCERE, T-MAHAL-ETIKET
    for layer_name in ("T-DUVAR", "T-KAPI", "T-PENCERE", "T-MAHAL-ETIKET"):
        if layer_name not in doc.layers:
            doc.layers.add(layer_name)

    if "TKAPI_90X220" not in doc.blocks:
        kapi = doc.blocks.new(name="TKAPI_90X220")
        kapi.add_line((-0.45, 0), (0.45, 0))
    if "TPENC_120X140" not in doc.blocks:
        pencere = doc.blocks.new(name="TPENC_120X140")
        pencere.add_line((-0.6, 0), (0.6, 0))

    msp = doc.modelspace()

    # 4 odali kucuk konut yerlesimi (farkli oda kodlari)
    rooms = [
        (0, 0, 5, 4, "K-101", "SALON"),
        (5, 0, 4, 4, "K-102", "MUTFAK"),
        (0, 4, 3, 3, "K-103", "BANYO"),
        (3, 4, 6, 3, "K-104", "YATAK ODASI"),
    ]
    for x, y, w, h, code, name in rooms:
        pts = [(x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y)]
        for a, b in zip(pts, pts[1:]):
            msp.add_line(a, b, dxfattribs={"layer": "T-DUVAR"})
        msp.add_mtext(
            f"{code}\\P{name}",
            dxfattribs={"layer": "T-MAHAL-ETIKET", "char_height": 0.25,
                        "insert": (x + w / 2, y + h / 2, 0)},
        )

    # Doors: SALON->MUTFAK, SALON->KORIDOR (BANYO/YATAK)
    msp.add_blockref("TKAPI_90X220", insert=(5, 2),
                     dxfattribs={"layer": "T-KAPI"})
    msp.add_blockref("TKAPI_90X220", insert=(2, 4),
                     dxfattribs={"layer": "T-KAPI"})
    msp.add_blockref("TKAPI_90X220", insert=(5, 4),
                     dxfattribs={"layer": "T-KAPI"})
    # Windows on the perimeter
    msp.add_blockref("TPENC_120X140", insert=(2, 0),
                     dxfattribs={"layer": "T-PENCERE"})
    msp.add_blockref("TPENC_120X140", insert=(7, 0),
                     dxfattribs={"layer": "T-PENCERE"})
    msp.add_blockref("TPENC_120X140", insert=(6, 7),
                     dxfattribs={"layer": "T-PENCERE"})

    doc.saveas(out)
    return out


if __name__ == "__main__":  # pragma: no cover
    import sys
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "data/samples/demo.dxf")
    if "alternate" in str(target):
        p = build_alternate_dxf(target)
    else:
        p = build_demo_dxf(target)
    print(f"DXF yazildi: {p}")
