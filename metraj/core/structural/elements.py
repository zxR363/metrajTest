"""Yapisal (kaba insaat) eleman veri modeli.

Mimari pipeline `Room/Opening/WallSegment` modelini kullanir; yapisal
metraj icin paralel bir model gerekir cunku hesap formulleri tamamen
farklidir (kalip m^2, beton m^3, kat tekrari, minha cikarimi).

Tum elemanlar `StructuralElement` ortak arayuzu uzerinden gezilir.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional, Tuple

from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry

ElementKind = Literal[
    "foundation",      # TEMEL
    "lean_concrete",   # GROBETON
    "column",          # KOLON
    "shear_wall",      # PERDE
    "beam",            # KIRIS
    "slab",            # DOSEME
    "slab_opening",    # DOSEME MINHA
    "parapet",         # PARAPET
    "stair",           # MERDIVEN
    "elevator_shaft",  # ASANSOR KULE
    "chimney",         # BACA
    "protection",      # KORUMA betonu
    "roof_slab",       # CATI dosemesi
]


@dataclass
class StructuralElement:
    """Tek bir yapisal eleman (kolon, perde, kiris, doseme, ...).

    Tum aciksal degerler metre ve metre^2 cinsindendir.
    """

    kind: ElementKind
    layer: str
    geom: BaseGeometry             # Polygon, MultiPolygon ya da LineString
    area_m2: float = 0.0           # plan goruntu alani
    perimeter_m: float = 0.0       # plan goruntu cevresi
    length_m: float = 0.0          # acik polyline icin uzunluk
    floor_label: Optional[str] = None  # "TEMEL", "0,00", "3,00", ...
    floor_index: Optional[int] = None  # 0=TEMEL, 1=0,00, 2=3,00, ...
    plan_index: Optional[int] = None   # DWG'de kacinci plan kumesi
    properties: Dict[str, float] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)

    @classmethod
    def from_polygon(
        cls,
        kind: ElementKind,
        layer: str,
        polygon: Polygon,
        floor_label: Optional[str] = None,
        floor_index: Optional[int] = None,
        plan_index: Optional[int] = None,
        properties: Optional[Dict[str, float]] = None,
    ) -> "StructuralElement":
        return cls(
            kind=kind,
            layer=layer,
            geom=polygon,
            area_m2=polygon.area,
            perimeter_m=polygon.length,
            length_m=0.0,
            floor_label=floor_label,
            floor_index=floor_index,
            plan_index=plan_index,
            properties=properties or {},
        )


@dataclass
class FloorPlan:
    """Bir kat plan kumesi (DWG'de yan yana cizilen plan dilimlerinden biri).

    `bbox` plan'in koordinat duzlemindeki sinirlarini verir; bu sayede
    eleman/etiket ataması mekanik olarak yapilabilir.
    """

    label: str                     # "TEMEL", "0,00", "3,00", ...
    index: int                     # sirali kat indeksi (0 = en alt)
    elevation_m: float             # +0.00, +3.00 (m)
    storey_height_m: float         # bu katin ust kotuna kadar olan yukseklik
    bbox: Tuple[float, float, float, float]  # (xmin, ymin, xmax, ymax)
    elements: List[StructuralElement] = field(default_factory=list)
    # "Tipik kat" plan kullanimi: ayni plan birkaç kati temsil ediyorsa
    # multiplier > 1 (orn. "2.VE 3. KAT" -> 2).  Calculate bunu carpan
    # olarak kullanir.
    multiplier: int = 1
    extra_labels: List[str] = field(default_factory=list)
    # Cogul kotlu plan icin altta kalan kotlar listesi (her kat icin
    # KOLON, KIRIS, DOSEME ayri kalemde uretilir).


@dataclass
class StructuralModel:
    """Tum yapisal elemanlar + kat plan listesi."""

    floors: List[FloorPlan] = field(default_factory=list)
    unassigned: List[StructuralElement] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def all_elements(self) -> List[StructuralElement]:
        out: List[StructuralElement] = []
        for f in self.floors:
            out.extend(f.elements)
        out.extend(self.unassigned)
        return out

    def by_kind(self, kind: ElementKind) -> List[StructuralElement]:
        return [e for e in self.all_elements() if e.kind == kind]
