"""Configuration objects loaded from YAML files in ``config/``.

These are the firma-specific mapping catalogs that the rest of the pipeline
relies on:

* ``layer_map.yaml`` -- maps DWG layer names to semantic roles
  (wall, room_label, door, window, hatch_floor, …).
* ``poz_library.yaml`` -- master poz catalog: poz no, kategori, birim, açıklama,
  birim fiyat.
* ``tip_definitions.yaml`` -- DŞ/DV/TV tip kodlarının poz dağılımı (kapllama
  reçetesi).  Tek mahalde birden çok kaplama olabildiği için her tip için
  yüzde dağılımı tutulur (toplam ≤ 1.0).
* ``project.yaml`` -- proje seviyesi ayarlar (kat şeması, varsayılan yükseklik
  bantları, kapı/pencere boyut yuvarlaması vs.).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence

import yaml

logger = logging.getLogger(__name__)


@dataclass
class LayerRole:
    """One semantic role assigned to one or more DWG layers."""

    role: str
    layers: List[str]
    notes: str = ""


@dataclass
class LayerMap:
    """Bidirectional layer <-> role lookup."""

    roles: Dict[str, LayerRole] = field(default_factory=dict)
    _layer_to_role: Dict[str, str] = field(default_factory=dict, repr=False)

    @classmethod
    def from_yaml(cls, path: str | Path) -> "LayerMap":
        with open(path, "r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
        return cls.from_dict(raw)

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "LayerMap":
        roles: Dict[str, LayerRole] = {}
        layer_index: Dict[str, str] = {}
        for role, conf in (data.get("roles") or {}).items():
            if isinstance(conf, list):
                layers = [str(l) for l in conf]
                notes = ""
            else:
                conf = conf or {}
                layers = [str(l) for l in (conf.get("layers") or [])]
                notes = str(conf.get("notes", ""))
            roles[role] = LayerRole(role=role, layers=layers, notes=notes)
            for l in layers:
                layer_index[l.upper()] = role
        instance = cls(roles=roles)
        instance._layer_to_role = layer_index
        return instance

    def role_of(self, layer: str) -> Optional[str]:
        if not layer:
            return None
        # Exact, case-insensitive
        role = self._layer_to_role.get(layer.upper())
        if role:
            return role
        # Wildcard fallback: roles can specify e.g. "A-DOOR*"
        for entry_layer, mapped_role in self._layer_to_role.items():
            if entry_layer.endswith("*") and layer.upper().startswith(entry_layer[:-1]):
                return mapped_role
        return None

    def layers_for(self, role: str) -> List[str]:
        entry = self.roles.get(role)
        return list(entry.layers) if entry else []

    def to_yaml(self, path: str | Path) -> None:
        out: Dict[str, Dict[str, object]] = {"roles": {}}
        for role, entry in self.roles.items():
            out["roles"][role] = {"layers": list(entry.layers), "notes": entry.notes}
        with open(path, "w", encoding="utf-8") as fh:
            yaml.safe_dump(out, fh, allow_unicode=True, sort_keys=False)


@dataclass
class PozEntry:
    poz_no: str
    kategori: str  # DOSEME / DUVAR / TAVAN / SUPURGELIK / DOGRAMA / KABUK ...
    tanim: str
    birim: str  # m2 | m | adet | m3
    birim_fiyat: float = 0.0


@dataclass
class PozLibrary:
    entries: Dict[str, PozEntry] = field(default_factory=dict)

    @classmethod
    def from_yaml(cls, path: str | Path) -> "PozLibrary":
        with open(path, "r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
        return cls.from_dict(raw)

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "PozLibrary":
        entries: Dict[str, PozEntry] = {}
        for poz_no, body in (data.get("pozlar") or {}).items():
            body = body or {}
            entries[poz_no] = PozEntry(
                poz_no=poz_no,
                kategori=str(body.get("kategori", "")).upper(),
                tanim=str(body.get("tanim", "")),
                birim=str(body.get("birim", "m2")),
                birim_fiyat=float(body.get("birim_fiyat", 0.0) or 0.0),
            )
        return cls(entries=entries)

    def get(self, poz_no: str) -> Optional[PozEntry]:
        return self.entries.get(poz_no)

    def by_kategori(self, kategori: str) -> List[PozEntry]:
        return [e for e in self.entries.values() if e.kategori == kategori.upper()]

    def to_yaml(self, path: str | Path) -> None:
        out = {"pozlar": {p.poz_no: {"kategori": p.kategori, "tanim": p.tanim,
                                     "birim": p.birim, "birim_fiyat": p.birim_fiyat}
                          for p in self.entries.values()}}
        with open(path, "w", encoding="utf-8") as fh:
            yaml.safe_dump(out, fh, allow_unicode=True, sort_keys=False)


@dataclass
class TipPozAssignment:
    poz_no: str
    pay: float = 1.0  # 0..1 yüzde dağılımı


@dataclass
class TipDefinition:
    code: str  # DŞ1, DV4, TV2, SP1 ...
    kategori: str  # DOSEME | DUVAR | TAVAN | SUPURGELIK
    pozlar: List[TipPozAssignment] = field(default_factory=list)
    tanim: str = ""


@dataclass
class TipDefinitions:
    tipler: Dict[str, TipDefinition] = field(default_factory=dict)

    @classmethod
    def from_yaml(cls, path: str | Path) -> "TipDefinitions":
        with open(path, "r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
        return cls.from_dict(raw)

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "TipDefinitions":
        tipler: Dict[str, TipDefinition] = {}
        for code, body in (data.get("tipler") or {}).items():
            body = body or {}
            pozlar = []
            for entry in body.get("pozlar") or []:
                if isinstance(entry, str):
                    pozlar.append(TipPozAssignment(poz_no=entry, pay=1.0))
                else:
                    pozlar.append(TipPozAssignment(
                        poz_no=str(entry["poz_no"]),
                        pay=float(entry.get("pay", 1.0)),
                    ))
            tipler[code] = TipDefinition(
                code=code,
                kategori=str(body.get("kategori", "")).upper(),
                tanim=str(body.get("tanim", "")),
                pozlar=pozlar,
            )
        return cls(tipler=tipler)

    def get(self, code: str) -> Optional[TipDefinition]:
        return self.tipler.get(code)


@dataclass
class FloorBand:
    """Kat tanimi: kod, ad, yukseklik (kot referansi)."""
    kod: str
    ad: str
    kot_alt: float
    kot_ust: float


@dataclass
class ProjectConfig:
    proje_adi: str = ""
    katlar: List[FloorBand] = field(default_factory=list)
    duvar_yukseklik_bantlari: List[float] = field(default_factory=lambda: [0.10, 0.15, 0.20, 0.30])
    kapi_yuvarlama_cm: float = 5.0  # snap door dimensions to 5cm bins
    pencere_yuvarlama_cm: float = 5.0

    @classmethod
    def from_yaml(cls, path: str | Path) -> "ProjectConfig":
        with open(path, "r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
        return cls.from_dict(raw)

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "ProjectConfig":
        katlar = [
            FloorBand(
                kod=str(k.get("kod", "")),
                ad=str(k.get("ad", "")),
                kot_alt=float(k.get("kot_alt", 0.0)),
                kot_ust=float(k.get("kot_ust", 0.0)),
            )
            for k in (data.get("katlar") or [])
        ]
        return cls(
            proje_adi=str(data.get("proje_adi", "")),
            katlar=katlar,
            duvar_yukseklik_bantlari=list(data.get("duvar_yukseklik_bantlari",
                                                  [0.10, 0.15, 0.20, 0.30])),
            kapi_yuvarlama_cm=float(data.get("kapi_yuvarlama_cm", 5.0)),
            pencere_yuvarlama_cm=float(data.get("pencere_yuvarlama_cm", 5.0)),
        )

    def kat_for_z(self, z: float) -> Optional[str]:
        for band in self.katlar:
            if band.kot_alt <= z <= band.kot_ust:
                return band.kod
        return None
