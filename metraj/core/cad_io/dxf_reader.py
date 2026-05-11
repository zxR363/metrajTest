"""DXF document reader producing a normalized in-memory model.

The reader collapses the DXF document into a small set of pure-Python
dataclasses that the rest of the pipeline operates on.  This isolates the
ezdxf API surface in one place so that future format support (IFC, Revit
RVT, plain GeoJSON ...) can plug in by emitting the same model.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import ezdxf
from ezdxf.document import Drawing
from ezdxf.entities import DXFEntity, Insert, MText, Text
from ezdxf.layouts import Modelspace

logger = logging.getLogger(__name__)

Point = Tuple[float, float]


@dataclass
class CadText:
    text: str
    layer: str
    insert: Point
    height: float = 0.0
    rotation: float = 0.0


@dataclass
class CadLine:
    start: Point
    end: Point
    layer: str

    def length(self) -> float:
        dx = self.end[0] - self.start[0]
        dy = self.end[1] - self.start[1]
        return math.hypot(dx, dy)


@dataclass
class CadPolyline:
    points: List[Point]
    layer: str
    closed: bool = False

    def length(self) -> float:
        total = 0.0
        for (x1, y1), (x2, y2) in zip(self.points, self.points[1:]):
            total += math.hypot(x2 - x1, y2 - y1)
        if self.closed and len(self.points) >= 2:
            x1, y1 = self.points[-1]
            x2, y2 = self.points[0]
            total += math.hypot(x2 - x1, y2 - y1)
        return total


@dataclass
class CadBlockRef:
    """Insert (block reference) with resolved attributes."""

    name: str
    layer: str
    insert: Point
    rotation: float = 0.0
    scale: Tuple[float, float] = (1.0, 1.0)
    attribs: Dict[str, str] = field(default_factory=dict)
    dynamic_params: Dict[str, str] = field(default_factory=dict)


@dataclass
class CadHatch:
    layer: str
    boundary: List[Point]
    pattern: str = ""


@dataclass
class RawCadModel:
    """Lightweight projection of the DXF document that downstream stages use."""

    source: Path
    units: str
    lines: List[CadLine] = field(default_factory=list)
    polylines: List[CadPolyline] = field(default_factory=list)
    texts: List[CadText] = field(default_factory=list)
    blocks: List[CadBlockRef] = field(default_factory=list)
    hatches: List[CadHatch] = field(default_factory=list)
    layers: List[str] = field(default_factory=list)
    block_definitions: List[str] = field(default_factory=list)
    #: Faz 1: katman -> ACI renk kodu (1..255). 256 = ByLayer (anlam: cizim sirasinda
    #: katmanin kendi rengi kullanilmasi gerek; burada katmana atanan rengi tutariz).
    #: 0 = ByBlock. Bilinmeyen/eksik katmanlar sozlukte bulunmaz.
    layer_colors: Dict[str, int] = field(default_factory=dict)

    def by_layer(self, layer: str) -> "RawCadModel":
        """Return a shallow projection containing entities on a given layer."""
        return RawCadModel(
            source=self.source,
            units=self.units,
            lines=[e for e in self.lines if e.layer == layer],
            polylines=[e for e in self.polylines if e.layer == layer],
            texts=[e for e in self.texts if e.layer == layer],
            blocks=[e for e in self.blocks if e.layer == layer],
            hatches=[e for e in self.hatches if e.layer == layer],
            layers=[layer],
            block_definitions=self.block_definitions,
        )

    def filter_layers(self, layers: Sequence[str]) -> "RawCadModel":
        layer_set = set(layers)
        return RawCadModel(
            source=self.source,
            units=self.units,
            lines=[e for e in self.lines if e.layer in layer_set],
            polylines=[e for e in self.polylines if e.layer in layer_set],
            texts=[e for e in self.texts if e.layer in layer_set],
            blocks=[e for e in self.blocks if e.layer in layer_set],
            hatches=[e for e in self.hatches if e.layer in layer_set],
            layers=list(layer_set),
            block_definitions=self.block_definitions,
        )


# Map DXF $INSUNITS code to a human label.  ezdxf reports these on the header.
_UNIT_LABELS = {
    0: "unitless",
    1: "inches",
    2: "feet",
    4: "mm",
    5: "cm",
    6: "m",
}


class DxfReader:
    """Read a DXF file into a normalized :class:`RawCadModel`.

    Parameters
    ----------
    target_unit:
        Output unit for all numeric values.  ``"m"`` matches the Excel
        groundtruth.  Conversions from inches/feet/mm/cm are handled
        automatically using the DXF ``$INSUNITS`` header code.
    explode_inserts:
        Faz 1: ``True`` ise her INSERT (block reference) icin block tanimindaki
        LWPOLYLINE / POLYLINE / CIRCLE / ARC / HATCH geometrileri INSERT'in
        konumuna gore transform edilerek `polylines` / `hatches` listelerine
        eklenir; layer = INSERT'in kendi katmanidir. Bu sayede kolon/kapi blok
        kullanan firma cizimlerinde block icindeki sekiller asagi pipeline'a
        gorunur. Varsayilan ``False`` (geri uyum).
    """

    def __init__(
        self,
        target_unit: str = "m",
        explode_inserts: bool = False,
    ) -> None:
        self.target_unit = target_unit
        self.explode_inserts = explode_inserts

    def read(self, dxf_path: str | Path) -> RawCadModel:
        path = Path(dxf_path)
        doc = ezdxf.readfile(path)
        unit_code = int(doc.header.get("$INSUNITS", 0) or 0)
        source_unit = _UNIT_LABELS.get(unit_code, "unitless")
        scale = self._unit_scale(source_unit, self.target_unit)
        model = RawCadModel(source=path, units=self.target_unit)
        msp = doc.modelspace()

        model.layers = sorted({layer.dxf.name for layer in doc.layers})
        model.block_definitions = sorted(b.name for b in doc.blocks if not b.name.startswith("*"))
        # Faz 1: katman renkleri (ACI). 7 (siyah/beyaz) default; ByLayer'i tutmuyoruz
        # cunku zaten katmanin kendisi.
        for lay in doc.layers:
            try:
                model.layer_colors[lay.dxf.name] = int(getattr(lay.dxf, "color", 7))
            except Exception:  # pragma: no cover
                pass

        self._doc = doc  # _collect_insert -> explode icin gecici referans
        for entity in msp:
            self._dispatch(entity, model, scale)
        self._doc = None  # type: ignore[assignment]
        logger.info(
            "DXF loaded: %d lines, %d polylines, %d texts, %d blocks, %d hatches "
            "across %d layers (unit=%s -> %s, scale=%.6f)",
            len(model.lines),
            len(model.polylines),
            len(model.texts),
            len(model.blocks),
            len(model.hatches),
            len(model.layers),
            source_unit,
            self.target_unit,
            scale,
        )
        return model

    @staticmethod
    def _unit_scale(source: str, target: str) -> float:
        meters = {
            "mm": 0.001,
            "cm": 0.01,
            "m": 1.0,
            "inches": 0.0254,
            "feet": 0.3048,
            "unitless": 1.0,
        }
        if source not in meters or target not in meters:
            return 1.0
        return meters[source] / meters[target]

    def _dispatch(self, entity: DXFEntity, model: RawCadModel, scale: float) -> None:
        dxftype = entity.dxftype()
        layer = entity.dxf.layer if hasattr(entity.dxf, "layer") else "0"
        try:
            if dxftype == "LINE":
                start = (entity.dxf.start.x * scale, entity.dxf.start.y * scale)
                end = (entity.dxf.end.x * scale, entity.dxf.end.y * scale)
                model.lines.append(CadLine(start=start, end=end, layer=layer))
            elif dxftype in {"LWPOLYLINE", "POLYLINE"}:
                pts = [(p[0] * scale, p[1] * scale) for p in entity.get_points("xy")] \
                    if dxftype == "LWPOLYLINE" else \
                    [(v.dxf.location.x * scale, v.dxf.location.y * scale) for v in entity.vertices]
                closed = bool(getattr(entity, "is_closed", False) or entity.dxf.flags & 1
                              if dxftype == "POLYLINE" else entity.closed)
                model.polylines.append(CadPolyline(points=pts, layer=layer, closed=closed))
            elif dxftype == "TEXT":
                self._collect_text(entity, model, scale, layer)
            elif dxftype == "MTEXT":
                self._collect_mtext(entity, model, scale, layer)
            elif dxftype == "INSERT":
                self._collect_insert(entity, model, scale, layer)
            elif dxftype == "HATCH":
                self._collect_hatch(entity, model, scale, layer)
            elif dxftype == "CIRCLE":
                cx, cy = entity.dxf.center.x * scale, entity.dxf.center.y * scale
                r = entity.dxf.radius * scale
                pts = [
                    (cx + r * math.cos(math.radians(a)), cy + r * math.sin(math.radians(a)))
                    for a in range(0, 360, 10)
                ]
                model.polylines.append(CadPolyline(points=pts, layer=layer, closed=True))
            elif dxftype == "ARC":
                pts = self._arc_points(entity, scale)
                model.polylines.append(CadPolyline(points=pts, layer=layer, closed=False))
        except Exception:  # pragma: no cover - defensive
            logger.exception("Failed to read DXF entity %s on layer %s", dxftype, layer)

    def _collect_text(self, entity: Text, model: RawCadModel, scale: float, layer: str) -> None:
        ins = entity.dxf.insert
        model.texts.append(
            CadText(
                text=str(entity.dxf.text or "").strip(),
                layer=layer,
                insert=(ins.x * scale, ins.y * scale),
                height=float(getattr(entity.dxf, "height", 0.0)) * scale,
                rotation=float(getattr(entity.dxf, "rotation", 0.0)),
            )
        )

    def _collect_mtext(self, entity: MText, model: RawCadModel, scale: float, layer: str) -> None:
        ins = entity.dxf.insert
        text = entity.plain_text() if hasattr(entity, "plain_text") else str(entity.text or "")
        model.texts.append(
            CadText(
                text=text.strip(),
                layer=layer,
                insert=(ins.x * scale, ins.y * scale),
                height=float(getattr(entity.dxf, "char_height", 0.0)) * scale,
                rotation=float(getattr(entity.dxf, "rotation", 0.0)),
            )
        )

    def _collect_insert(self, entity: Insert, model: RawCadModel, scale: float, layer: str) -> None:
        attribs: Dict[str, str] = {}
        for att in entity.attribs:
            try:
                attribs[att.dxf.tag] = str(att.dxf.text or "").strip()
            except Exception:
                continue
        dynamic: Dict[str, str] = {}
        try:  # ezdxf >= 1.x exposes block_state for dynamic blocks
            if entity.has_xdata("ACAD"):
                xd = entity.get_xdata("ACAD")
                for code, value in xd:
                    dynamic.setdefault(str(code), str(value))
        except Exception:
            pass
        ins = entity.dxf.insert
        sx = float(getattr(entity.dxf, "xscale", 1.0))
        sy = float(getattr(entity.dxf, "yscale", 1.0))
        model.blocks.append(
            CadBlockRef(
                name=entity.dxf.name,
                layer=layer,
                insert=(ins.x * scale, ins.y * scale),
                rotation=float(getattr(entity.dxf, "rotation", 0.0)),
                scale=(sx, sy),
                attribs=attribs,
                dynamic_params=dynamic,
            )
        )

        # Faz 1: opsiyonel block-explode. Block tanimindaki LWPOLYLINE/POLYLINE/
        # CIRCLE/ARC/HATCH alt entity'lerini INSERT transform ile model'e ekler;
        # alt entity'lerin katmanini INSERT'in katmaniyla override ederiz, cunku
        # firma cogu zaman block'u STRUCT katmanina yerlestirir ama block icindeki
        # cizgiler "0" katmaninda olur (ByLayer).
        if not self.explode_inserts:
            return
        try:
            for sub in entity.virtual_entities():
                try:
                    sub.dxf.layer = layer
                except Exception:
                    pass
                # Recursion sonsuz olmasin: nested INSERT'i tekrar explode etmiyoruz
                # cunku virtual_entities() zaten nested'i acar. Yine de guvenlik
                # icin INSERT alt-tipini bilek bekkit'le isaretliyoruz.
                if sub.dxftype() == "INSERT":
                    continue
                self._dispatch(sub, model, scale)
        except Exception:  # pragma: no cover - defensive
            logger.exception("INSERT explode basarisiz: %s on %s",
                             entity.dxf.name, layer)

    def _collect_hatch(self, entity, model: RawCadModel, scale: float, layer: str) -> None:
        boundary: List[Point] = []
        try:
            for path in entity.paths:
                for vertex in path.vertices:
                    boundary.append((vertex[0] * scale, vertex[1] * scale))
                if boundary:
                    break
        except Exception:
            return
        if boundary:
            model.hatches.append(
                CadHatch(layer=layer, boundary=boundary, pattern=getattr(entity.dxf, "pattern_name", "") or "")
            )

    def _arc_points(self, entity, scale: float, n: int = 16) -> List[Point]:
        cx, cy = entity.dxf.center.x * scale, entity.dxf.center.y * scale
        r = entity.dxf.radius * scale
        a0 = math.radians(entity.dxf.start_angle)
        a1 = math.radians(entity.dxf.end_angle)
        if a1 < a0:
            a1 += 2 * math.pi
        return [
            (cx + r * math.cos(a0 + (a1 - a0) * i / (n - 1)),
             cy + r * math.sin(a0 + (a1 - a0) * i / (n - 1)))
            for i in range(n)
        ]


def inventory_layers(model: RawCadModel) -> Dict[str, Dict[str, int]]:
    """Return a per-layer count of entities by category, useful for Faz 0."""
    counts: Dict[str, Dict[str, int]] = {layer: {"line": 0, "polyline": 0, "text": 0,
                                                "block": 0, "hatch": 0}
                                         for layer in model.layers}
    for line in model.lines:
        counts.setdefault(line.layer, {"line": 0, "polyline": 0, "text": 0, "block": 0, "hatch": 0})
        counts[line.layer]["line"] += 1
    for pl in model.polylines:
        counts.setdefault(pl.layer, {"line": 0, "polyline": 0, "text": 0, "block": 0, "hatch": 0})
        counts[pl.layer]["polyline"] += 1
    for t in model.texts:
        counts.setdefault(t.layer, {"line": 0, "polyline": 0, "text": 0, "block": 0, "hatch": 0})
        counts[t.layer]["text"] += 1
    for b in model.blocks:
        counts.setdefault(b.layer, {"line": 0, "polyline": 0, "text": 0, "block": 0, "hatch": 0})
        counts[b.layer]["block"] += 1
    for h in model.hatches:
        counts.setdefault(h.layer, {"line": 0, "polyline": 0, "text": 0, "block": 0, "hatch": 0})
        counts[h.layer]["hatch"] += 1
    return counts


def inventory_blocks(model: RawCadModel) -> Dict[str, int]:
    """Per-block-definition usage counts."""
    counts: Dict[str, int] = {}
    for b in model.blocks:
        counts[b.name] = counts.get(b.name, 0) + 1
    return counts
