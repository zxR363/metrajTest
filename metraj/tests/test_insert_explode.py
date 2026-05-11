"""INSERT explode (Faz 1) testleri.

Sentetik bir DXF uretilir: kolon poligonlari **block tanimi** icine konur ve
modelspace'e INSERT olarak yerlestirilir. Default DxfReader bunlari `model.blocks`
listesine eklerken `model.polylines` bos kalir; `explode_inserts=True` ile alt
polyline'lar transform edilerek `model.polylines`'a duser.

Boylece kolon/kapi bloku kullanan firma cizimlerinde Faz 1 INSERT explode'un
gercekten kolon sayisini 0 -> N artirdigini kanitlariz.
"""
from __future__ import annotations

from pathlib import Path

import ezdxf
import pytest

from metraj.core.cad_io.dxf_reader import DxfReader


def _build_insert_only_columns_dxf(out_path: Path, n_columns: int = 8) -> Path:
    """``n_columns`` adet kapali 0.7x0.5 kolon poligonu block icinde, modelspace'te
    INSERT olarak yerlestirilir.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc = ezdxf.new(setup=True, dxfversion="R2018")
    doc.header["$INSUNITS"] = 6  # meters

    # KOLON NA katmani — Kumluca tarzi, renk = 2 (sari)
    if "KOLON NA" not in doc.layers:
        doc.layers.add("KOLON NA", color=2)

    # Block tanimi: 0.7x0.5 kapali kolon poligonu (block icindeki origin 0,0)
    if "COL_70x50" not in doc.blocks:
        blk = doc.blocks.new(name="COL_70x50")
        blk.add_lwpolyline(
            points=[(0, 0), (0.7, 0), (0.7, 0.5), (0, 0.5)],
            close=True,
            dxfattribs={"layer": "0"},  # block icindeki cizgi "0" (ByLayer)
        )

    msp = doc.modelspace()
    # Modelspace'te `n_columns` INSERT; her biri farkli konumda
    for i in range(n_columns):
        msp.add_blockref(
            "COL_70x50",
            insert=(i * 5.0, 0),
            dxfattribs={"layer": "KOLON NA"},
        )

    doc.saveas(out_path)
    return out_path


def test_insert_default_does_not_create_polylines(tmp_path):
    """``explode_inserts=False`` (default): INSERT polyline'lari `model.polylines`'a
    eklenmez, yalniz `model.blocks` listesinde gorunur."""
    dxf = _build_insert_only_columns_dxf(tmp_path / "insert_only.dxf", n_columns=5)

    reader = DxfReader()  # default: explode_inserts=False
    model = reader.read(dxf)

    assert len(model.blocks) == 5
    # KOLON NA katmaninda kapali polyline yok (sadece block ref'ler var)
    kolon_polys = [p for p in model.polylines if p.layer == "KOLON NA" and p.closed]
    assert kolon_polys == []


def test_insert_explode_unlocks_columns(tmp_path):
    """``explode_inserts=True``: block icindeki polyline INSERT'in katmaniyla
    `model.polylines`'a eklenir; kolon sayisi 5 olur."""
    dxf = _build_insert_only_columns_dxf(tmp_path / "insert_only.dxf", n_columns=5)

    reader = DxfReader(explode_inserts=True)
    model = reader.read(dxf)

    assert len(model.blocks) == 5  # bilgi amacli hala tutulur
    kolon_polys = [p for p in model.polylines if p.layer == "KOLON NA" and p.closed]
    assert len(kolon_polys) == 5, (
        f"INSERT explode kolon polyline uretmeli (5 INSERT × 1 closed poly = 5), "
        f"bulunan: {len(kolon_polys)}"
    )

    # Layer renk DXF'ten okunmus olmali (Faz 1 layer_colors)
    assert model.layer_colors.get("KOLON NA") == 2


def test_explode_preserves_layer_colors(tmp_path):
    """layer_colors sozlugu DXF'ten okunmali; explode'tan bagimsiz calismali."""
    dxf = _build_insert_only_columns_dxf(tmp_path / "insert_only.dxf", n_columns=2)
    reader = DxfReader()  # explode kapali bile olsa layer_colors dolmali
    model = reader.read(dxf)
    assert model.layer_colors.get("KOLON NA") == 2
