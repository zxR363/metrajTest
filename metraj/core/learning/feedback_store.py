"""Faz 5: Proje bazli kullanici geri-bildirim deposu (JSON).

UI veya CLI uzerinden kullanici, otomatik tanima/sinflandirma yanlislari icin
**override** kaydeder. Pipeline, bu override'lari mevcut ``StructuralConfig``
mekanizmalariyla (``structural_layer_include_kind``, ``comparison_label_aliases``,
``structural_layer_exclude``) birlikte uygular — **sessiz overwrite YOK**, opt-in.

Veri modeli (JSON ``schema_version=1``):

.. code-block:: json

   {
     "schema_version": 1,
     "project_name": "Proje A",
     "layer_kind_overrides": {"KOL-30x60": "column"},
     "comparison_alias_overrides": {"BLOK_A": "0,00 BLOK"},
     "excluded_layers": ["IZ_KOLON_PRY"],
     "manual_classifications": [
       {"layer": "KOLON NA", "centroid": [120.5, 5.0], "kind": "shear_wall",
        "reason": "aspect=19 perde"}
     ],
     "notes": ["..."]
   }

Multi-proje global hint cikarimi:
* ``extract_global_hints([store1, store2, store3])`` — birden fazla projede
  ayni override goren satirlari "global ipucu" olarak konsolide eder; cikti
  ``signal_hints`` formatinda YAML'a yazilabilir.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1


@dataclass
class ManualClassification:
    """Kullanici elemana ozel siniflandirma overrideai (UI polygon-click).

    ``centroid``: eleman geometrisinin yaklasik merkezi (m); pipeline yeniden
    kosulurken (DXF degisebilir) tam ayni eleman bulunamayabilir, en yakin
    merkeze sahip ayni-kind eleman secilir.
    """

    layer: str
    centroid: Tuple[float, float]
    kind: str
    reason: str = ""


@dataclass
class FeedbackStore:
    """Tek bir proje icin override'lar."""

    project_name: str = ""
    #: Katman adi -> ElementKind override (autodetect uzerine yazar). Mevcut
    #: ``StructuralConfig.structural_layer_include_kind`` ile birlestirilir.
    layer_kind_overrides: Dict[str, str] = field(default_factory=dict)
    #: Comparison key alias override (gt_io.comparison_key). Mevcut
    #: ``comparison_label_aliases`` ile birlestirilir.
    comparison_alias_overrides: Dict[str, str] = field(default_factory=dict)
    #: Pipeline'in autodetect ettigi katmanlardan geometri cikarmasini engeller.
    excluded_layers: List[str] = field(default_factory=list)
    #: Polygon-click ile eleman bazinda kind override (Faz 5 v2'de pipeline'a entegre edilir).
    manual_classifications: List[ManualClassification] = field(default_factory=list)
    #: Insan-okunabilir notlar (UI uyari sayfasinda gosterilir).
    notes: List[str] = field(default_factory=list)
    #: Kaynak JSON dosyasi (kayit/loglama icin); load() doldurur.
    source_path: Optional[Path] = None

    # -----------------------------------------------------------------
    # JSON load / save
    # -----------------------------------------------------------------

    @classmethod
    def load(cls, path: str | Path) -> "FeedbackStore":
        """JSON dosyasini yukler. Dosya yoksa bos store doner."""
        p = Path(path)
        if not p.is_file():
            return cls(source_path=p)
        with open(p, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            raise ValueError(f"feedback JSON kok nesnesi sozluk olmali: {p}")
        ver = int(data.get("schema_version", 1))
        if ver != SCHEMA_VERSION:
            logger.warning("feedback JSON schema_version=%d != %d (best-effort)",
                           ver, SCHEMA_VERSION)
        manuals_raw = data.get("manual_classifications") or []
        manuals: List[ManualClassification] = []
        for m in manuals_raw:
            try:
                centroid = m["centroid"]
                manuals.append(ManualClassification(
                    layer=str(m["layer"]),
                    centroid=(float(centroid[0]), float(centroid[1])),
                    kind=str(m["kind"]),
                    reason=str(m.get("reason", "")),
                ))
            except (KeyError, TypeError, ValueError, IndexError):
                logger.warning("feedback manual_classification gecersiz: %r", m)
        return cls(
            project_name=str(data.get("project_name", "")),
            layer_kind_overrides={
                str(k): str(v) for k, v in (data.get("layer_kind_overrides") or {}).items()
            },
            comparison_alias_overrides={
                str(k): str(v) for k, v in (data.get("comparison_alias_overrides") or {}).items()
            },
            excluded_layers=[str(x) for x in (data.get("excluded_layers") or [])],
            manual_classifications=manuals,
            notes=[str(x) for x in (data.get("notes") or [])],
            source_path=p,
        )

    def save(self, path: Optional[str | Path] = None) -> Path:
        """JSON'a yazar. ``path`` verilmezse ``source_path`` kullanilir."""
        out_path = Path(path) if path else self.source_path
        if out_path is None:
            raise ValueError("FeedbackStore.save: path/source_path bos")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        payload: Dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "project_name": self.project_name,
            "layer_kind_overrides": dict(self.layer_kind_overrides),
            "comparison_alias_overrides": dict(self.comparison_alias_overrides),
            "excluded_layers": list(self.excluded_layers),
            "manual_classifications": [asdict(m) for m in self.manual_classifications],
            "notes": list(self.notes),
        }
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        self.source_path = out_path
        return out_path

    # -----------------------------------------------------------------
    # In-place edit helpers (CLI / UI icin)
    # -----------------------------------------------------------------

    def set_layer_kind(self, layer: str, kind: str) -> None:
        self.layer_kind_overrides[str(layer)] = str(kind)

    def remove_layer_kind(self, layer: str) -> bool:
        return self.layer_kind_overrides.pop(str(layer), None) is not None

    def set_alias(self, src: str, dst: str) -> None:
        self.comparison_alias_overrides[str(src)] = str(dst)

    def exclude_layer(self, layer: str) -> None:
        lay = str(layer)
        if lay not in self.excluded_layers:
            self.excluded_layers.append(lay)

    def add_manual_classification(self, mc: ManualClassification) -> None:
        self.manual_classifications.append(mc)

    # -----------------------------------------------------------------
    # Pipeline'a uygulama (StructuralConfig override merge)
    # -----------------------------------------------------------------

    def apply_to_config_dicts(
        self,
        layer_kind_dict: Dict[str, str],
        alias_dict: Dict[str, str],
        excluded_list: List[str],
    ) -> None:
        """Mevcut ``StructuralConfig`` dict'lerini in-place merge eder.

        FeedbackStore override'lari config uzerinde **oncelikli**: YAML'da
        yazili alanlar feedback ile cakisirsa feedback kazanir (kullanici son
        kararidir).
        """
        layer_kind_dict.update(self.layer_kind_overrides)
        alias_dict.update(self.comparison_alias_overrides)
        for lay in self.excluded_layers:
            if lay not in excluded_list:
                excluded_list.append(lay)


# ---------------------------------------------------------------------------
# Multi-proje: global hint cikarimi
# ---------------------------------------------------------------------------


@dataclass
class GlobalHint:
    """Birden fazla projede ayni override goruldu — global ipucu."""

    kind: str          # "layer_kind" / "comparison_alias"
    source: str        # override anahtari (layer name veya alias src)
    target: str        # override degeri (ElementKind veya alias dst)
    project_count: int
    projects: List[str]


def extract_global_hints(
    stores: Sequence[FeedbackStore],
    min_project_count: int = 2,
) -> List[GlobalHint]:
    """N projeden ortak override'lari konsolide eder.

    Sadece ``min_project_count`` veya daha fazla projede ayni (kaynak, hedef)
    cifti goruldugunde global hint olur. Tek-projedeki ozel overrideleri global
    listeye sokmayız — overfit riski.
    """
    layer_kind_votes: Dict[Tuple[str, str], List[str]] = {}
    alias_votes: Dict[Tuple[str, str], List[str]] = {}

    for s in stores:
        proj = s.project_name or (s.source_path.stem if s.source_path else "?")
        for layer, kind in s.layer_kind_overrides.items():
            key = (str(layer), str(kind))
            layer_kind_votes.setdefault(key, []).append(proj)
        for src, dst in s.comparison_alias_overrides.items():
            key = (str(src), str(dst))
            alias_votes.setdefault(key, []).append(proj)

    out: List[GlobalHint] = []
    for (layer, kind), projects in layer_kind_votes.items():
        if len(projects) >= min_project_count:
            out.append(GlobalHint(
                kind="layer_kind", source=layer, target=kind,
                project_count=len(projects), projects=list(projects),
            ))
    for (src, dst), projects in alias_votes.items():
        if len(projects) >= min_project_count:
            out.append(GlobalHint(
                kind="comparison_alias", source=src, target=dst,
                project_count=len(projects), projects=list(projects),
            ))
    out.sort(key=lambda g: (-g.project_count, g.kind, g.source))
    return out


def global_hints_to_signal_hints_yaml(
    hints: Sequence[GlobalHint],
) -> Dict[str, Any]:
    """``GlobalHint``'leri ``signal_hints`` YAML formatina cevirir.

    Sadece ``layer_kind`` hint'lerini ``name_aliases`` blogunda toplar; alias
    hint'leri ayri liste olarak doner.
    """
    name_aliases: Dict[str, List[str]] = {}
    alias_pairs: Dict[str, str] = {}
    for h in hints:
        if h.kind == "layer_kind":
            name_aliases.setdefault(h.target, []).append(h.source)
        elif h.kind == "comparison_alias":
            alias_pairs[h.source] = h.target

    out: Dict[str, Any] = {}
    if name_aliases:
        out["name_aliases"] = {k: sorted(set(v)) for k, v in name_aliases.items()}
    if alias_pairs:
        out["comparison_label_aliases"] = dict(sorted(alias_pairs.items()))
    return out


def load_stores_from_dir(directory: str | Path) -> List[FeedbackStore]:
    """Klasordeki tum ``*.json`` feedback dosyalarini yukler."""
    d = Path(directory)
    if not d.is_dir():
        return []
    return [FeedbackStore.load(p) for p in sorted(d.glob("*.json"))]


__all__ = [
    "FeedbackStore",
    "ManualClassification",
    "GlobalHint",
    "extract_global_hints",
    "global_hints_to_signal_hints_yaml",
    "load_stores_from_dir",
    "SCHEMA_VERSION",
]
