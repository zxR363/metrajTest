"""Excel-bagimsiz yapisal metraj konfigurasyon sihirbazi.

Kullanici elinde referans Excel olmasa bile, **saf geometri + UI uzerinden
sayim usulu ayarlama** ile metraj hesaplamasi yapabilir.

Akis:
  1. Preset sec ("Saf geometri", "Kumluca tarzi yari kesit", veya custom)
  2. Anlasiliř etiketlerle gruplandirilmis form uzerinden:
     - Kolon kalibi: tam cevre / yari / ozel
     - Kiris derinligi, genisligi
     - Doseme kalinligi, eksiltme dahil mi
     - Parapet kalinligi, yuksekligi
     - Asansor: her sahti ayri / toplu
  3. YAML kaydet (compare_to_reference=false, excel_layout=generic)
  4. Bu YAML ile `metraj run --mode structural` koshturulur

GUI yokken non-GUI helper'lar:
  - ``load_method_preset(name) -> CalcParams``
  - ``calcparams_to_yaml(cp, path)``
  - ``FIELD_GROUPS`` — yapilandirma grup tanimlari (UI tarafindan tuketilir)
"""
from __future__ import annotations

import logging
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

logger = logging.getLogger(__name__)

try:
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QComboBox,
        QDialog,
        QDialogButtonBox,
        QDoubleSpinBox,
        QFileDialog,
        QFormLayout,
        QGroupBox,
        QHBoxLayout,
        QHeaderView,
        QLabel,
        QLineEdit,
        QListWidget,
        QMessageBox,
        QPushButton,
        QTableWidget,
        QTableWidgetItem,
        QTabWidget,
        QTextEdit,
        QVBoxLayout,
        QWidget,
    )

    PYSIDE_AVAILABLE = True
except ImportError:  # pragma: no cover
    PYSIDE_AVAILABLE = False


from ..core.structural.calculator import CalcParams


# ---------------------------------------------------------------------------
# Field group tanimlari — UI tarafi bu sozlukten form uretir
# ---------------------------------------------------------------------------


@dataclass
class FieldDef:
    """UI form alani tanimi."""

    name: str                # CalcParams alan adi
    label: str               # Kullanici-okur etiket
    description: str         # Tooltip / aciklama
    min_value: float = 0.0
    max_value: float = 100.0
    decimals: int = 4
    step: float = 0.05
    unit: str = ""           # "m" / "m²" / "—" / "%" gibi


# Mantikli gruplandirma — UI'de QTabWidget olarak gosterilir
FIELD_GROUPS: Dict[str, List[FieldDef]] = {
    "Kolon (column)": [
        FieldDef(
            "column_formwork_strip_fraction",
            "Kolon kalip cevre carpani",
            "Kolon kalibi = polygon cevresi × bu carpan × kat yuksekligi.\n"
            "1.0 = tum yuzeyler (tam cevre), 0.5 = iki taraf serit (yari cevre).",
            min_value=0.0, max_value=2.0, step=0.05,
        ),
        FieldDef(
            "column_concrete_section_fraction",
            "Kolon beton kesit carpani",
            "Kolon beton = polygon alani × bu carpan × kat yuksekligi.\n"
            "1.0 = tam kesit alani, 0.5 = yarisi (cift polyline pratigi).",
            min_value=0.0, max_value=2.0, step=0.05,
        ),
    ],
    "Perde (shear_wall)": [
        FieldDef(
            "shear_wall_concrete_section_fraction",
            "Perde beton kesit carpani",
            "Perde beton = polygon alani × bu carpan × kat yuksekligi.",
            min_value=0.0, max_value=2.0, step=0.05,
        ),
    ],
    "Kiris (beam)": [
        FieldDef(
            "beam_depth_m",
            "Kiris derinligi (m)",
            "Kiris kalip yuksekligi (doseme altindan).",
            min_value=0.1, max_value=2.0, step=0.05, unit="m",
        ),
        FieldDef(
            "beam_width_m",
            "Kiris genisligi (m)",
            "Kiris alt yuz olcumunde kullanilan genisilik.",
            min_value=0.1, max_value=1.0, step=0.05, unit="m",
        ),
        FieldDef(
            "beam_formwork_length_fraction",
            "Kiris kalip uzunluk carpani",
            "Kiris kalip = uzunluk × bu carpan × derinlik.\n"
            "1.0 = tam uzunluk, 0.5 = sadece taban+1 yan.",
            min_value=0.0, max_value=2.0, step=0.05,
        ),
        FieldDef(
            "beam_concrete_section_fraction",
            "Kiris beton kesit carpani",
            "Kiris beton = polygon alani × bu carpan × derinlik.",
            min_value=0.0, max_value=2.0, step=0.05,
        ),
    ],
    "Doseme (slab)": [
        FieldDef(
            "slab_thickness_m",
            "Doseme kalinligi (m)",
            "Doseme yatay kesit kalinligi (beton hacmi icin).",
            min_value=0.05, max_value=1.0, step=0.01, unit="m",
        ),
        FieldDef(
            "slab_net_area_fraction",
            "Doseme net alan carpani",
            "Doseme = polygon alani × bu carpan.\n"
            "1.0 = brut alan, 0.5 = yari (firma usulu).",
            min_value=0.0, max_value=2.0, step=0.05,
        ),
    ],
    "Temel & Grobeton": [
        FieldDef(
            "foundation_depth_m",
            "Temel derinligi (m)",
            "Radye temel kalinligi (beton hacmi icin).",
            min_value=0.1, max_value=2.0, step=0.05, unit="m",
        ),
        FieldDef(
            "foundation_plan_formwork_scale",
            "Temel kalip cevre carpani",
            "Temel kalibi (radyye yan yuzeyleri) carpani.",
            min_value=0.0, max_value=2.0, step=0.05,
        ),
        FieldDef(
            "foundation_concrete_section_fraction",
            "Temel beton kesit carpani",
            "Radye beton kesit alani carpani.",
            min_value=0.0, max_value=2.0, step=0.05,
        ),
        FieldDef(
            "lean_concrete_thickness_m",
            "Grobeton kalinligi (m)",
            "Temel alti koruyucu beton tabakasi.",
            min_value=0.02, max_value=0.30, step=0.01, unit="m",
        ),
        FieldDef(
            "grobeton_formwork_gt_scale",
            "Grobeton kalip carpani",
            "Grobeton yan yuzeyleri carpani.",
            min_value=0.0, max_value=2.0, step=0.05,
        ),
    ],
    "Parapet & Asansor": [
        FieldDef(
            "parapet_thickness_m",
            "Parapet kalinligi (m)",
            "Parapet duvar et kalinligi.",
            min_value=0.05, max_value=0.50, step=0.01, unit="m",
        ),
        FieldDef(
            "parapet_concrete_volume_fraction",
            "Parapet beton hacim carpani",
            "Parapet beton = alan × kalinlik × bu carpan.",
            min_value=0.0, max_value=2.0, step=0.05,
        ),
        FieldDef(
            "elevator_shaft_quantity_scale",
            "Asansor sahti carpani",
            "1.0 = her sahti ayri kalem.\n"
            "0.333 = 3 sahti tek kalemde topla (Kumluca usulü).",
            min_value=0.0, max_value=2.0, step=0.05,
        ),
        FieldDef(
            "elevator_extra_height_m",
            "Asansor ek yukseklik (m)",
            "Asansor kulesi cati uzerinde ek yukseklik (motor odasi).",
            min_value=0.0, max_value=5.0, step=0.05, unit="m",
        ),
        FieldDef(
            "chimney_height_m",
            "Baca yuksekligi (m)",
            "Baca kalibi hesaplaminda kullanilan ortalama yukseklik.",
            min_value=0.0, max_value=3.0, step=0.05, unit="m",
        ),
    ],
    "Minha & Eksiltmeler": [
        FieldDef(
            "slab_opening_concrete_scale",
            "Doseme bosluk minha beton carpani",
            "Doseme bosluk (minha) beton hacmi carpani.\n"
            "1.0 = tam bosluk hacmi dusulur, 0.5 = yari, 0 = dusulmez.\n"
            "Kumluca'da 0.906.",
            min_value=0.0, max_value=2.0, step=0.05,
        ),
        FieldDef(
            "kolon_head_minha_scale",
            "Kolon yerleri minha global carpani",
            "Tum katlarda KOLON YERLERI MINHA (kolon basligi yeri dusurme) carpani.\n"
            "1.0 = tam dusurulur, 0.807 = Kumluca usulu (6 kat tek blok).",
            min_value=0.0, max_value=2.0, step=0.05,
        ),
        FieldDef(
            "beam_join_minha_m",
            "Kiris birlesim minha (m)",
            "Kiris birlesim noktalarinda dusen yukseklik (m).\n"
            "Tipik 0.135 m.",
            min_value=0.0, max_value=0.5, step=0.005, unit="m",
        ),
        FieldDef(
            "beam_zemin_concrete_qty_scale",
            "Zemin kiris beton ozel carpani",
            "ZEMIN (0,00) katindaki kiris beton qty1 ek olcek.\n"
            "Kumluca'da 0.434 (zemin kirisi ust kattan farkli).\n"
            "1.0 = digerleri ile ayni.",
            min_value=0.0, max_value=2.0, step=0.05,
        ),
    ],
    "Cati & Koruma": [
        FieldDef(
            "roof_slab_thickness_m",
            "Cati doseme kalinligi (m)",
            "Cati dosememe (terras) kalinligi.",
            min_value=0.05, max_value=0.50, step=0.01, unit="m",
        ),
        FieldDef(
            "roof_protection_thickness_m",
            "Cati koruma betonu kalinligi (m)",
            "Cati uzeri koruma sap kalinligi.",
            min_value=0.02, max_value=0.20, step=0.01, unit="m",
        ),
        FieldDef(
            "beam_height_m",
            "Kiris yuksekligi (m)",
            "Kiris geometrik yukseklik (bazi hesaplarda).",
            min_value=0.1, max_value=2.0, step=0.05, unit="m",
        ),
    ],
}


# ---------------------------------------------------------------------------
# Non-GUI helper'lar — test edilebilir
# ---------------------------------------------------------------------------


_METHODS_DIR = Path(__file__).resolve().parents[1] / "config" / "methods"


def list_method_presets() -> List[str]:
    """``config/methods/*.yaml`` icindeki preset isimlerini doner."""
    if not _METHODS_DIR.is_dir():
        return []
    return sorted(p.stem for p in _METHODS_DIR.glob("*.yaml"))


def load_method_preset(name: str) -> CalcParams:
    """Preset YAML'den ``CalcParams`` yukler.

    ``name`` parametre olarak preset stem'i (ornek: ``geometry_full``,
    ``geometry_half``, ``custom_template``) verilir.
    """
    path = _METHODS_DIR / f"{name}.yaml"
    if not path.is_file():
        raise FileNotFoundError(f"Preset bulunamadi: {path}")
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    params_raw = (data.get("params") or {}) if isinstance(data, dict) else {}
    cp = CalcParams()
    for k, v in params_raw.items():
        if not hasattr(cp, k):
            continue
        # Dict alanlari (kat-bazli) direkt ata
        if isinstance(v, dict):
            try:
                setattr(cp, k, {str(kk): float(vv) for kk, vv in v.items()})
            except (TypeError, ValueError):
                continue
        else:
            try:
                setattr(cp, k, float(v))
            except (TypeError, ValueError):
                continue
    return cp


def calcparams_to_yaml(
    cp: CalcParams,
    output_path: str | Path,
    *,
    project_name: str = "Custom (no reference Excel)",
    excel_layout: str = "generic",
    structural_layer_include_kind: Optional[Dict[str, str]] = None,
    structural_layer_exclude: Optional[List[str]] = None,
) -> Path:
    """``CalcParams``'i StructuralConfig.from_file uyumlu YAML'a yazar.

    ``compare_to_reference=false`` ve ``excel_layout=generic`` olarak set
    edilir (Excel'siz mod). Opsiyonel olarak katman override sozlugu ve
    dislama listesi de yaml'a yazilir.
    """
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    default = CalcParams()
    params_diff: Dict[str, Any] = {}
    for fld in cp.__dataclass_fields__:
        if fld == "storey_heights":
            continue
        val = getattr(cp, fld)
        dval = getattr(default, fld)
        if isinstance(val, dict):
            if val:
                params_diff[fld] = dict(val)
        elif isinstance(val, (int, float)):
            if abs(float(val) - float(dval)) > 1e-9:
                params_diff[fld] = float(val)
        elif val != dval:
            params_diff[fld] = val

    payload: Dict[str, Any] = {
        "project_name": project_name,
        "excel_layout": excel_layout,
        "compare_to_reference": False,
        "snap_rows_to_reference": False,
        "params": params_diff,
    }
    if structural_layer_include_kind:
        payload["structural_layer_include_kind"] = dict(structural_layer_include_kind)
    if structural_layer_exclude:
        payload["structural_layer_exclude"] = list(structural_layer_exclude)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write("# Excel-bagimsiz yapisal metraj profili (config-wizard cikti)\n\n")
        yaml.safe_dump(payload, fh, allow_unicode=True, sort_keys=False)
    return out


def field_groups_to_flat_list() -> List[FieldDef]:
    """Tum gruplari tek listede birlestirir (test ve introspection icin)."""
    flat: List[FieldDef] = []
    for fields in FIELD_GROUPS.values():
        flat.extend(fields)
    return flat


# ---------------------------------------------------------------------------
# GUI (PySide6 varsa)
# ---------------------------------------------------------------------------


if PYSIDE_AVAILABLE:

    # Hangi CalcParams dict alanlari "Kat-bazli Ayarlar" sekmesinde gosterilir
    _FLOOR_DICT_FIELDS = [
        ("doseme_net_scale_by_floor_label",
         "Doseme kalip kat-bazli carpan",
         "Belirli katlarda DOSEME KALIP carpani (orn. 0,00=1.04). Kumluca'da kat-bazli."),
        ("doseme_concrete_net_scale_by_floor_label",
         "Doseme beton kat-bazli carpan",
         "Belirli katlarda DOSEME BETON carpani."),
        ("beam_formwork_floor_scale",
         "Kiris kalip kat-bazli carpan",
         "Belirli katlarda KIRIS KALIP carpani (orn. 0,00=0.97)."),
        ("beam_concrete_floor_scale",
         "Kiris beton kat-bazli carpan",
         "Belirli katlarda KIRIS BETON carpani."),
        ("parapet_formwork_floor_scale",
         "Parapet kalip kat-bazli carpan",
         "Belirli katlarda PARAPET KALIP carpani."),
        ("beam_join_minha_floor_scale",
         "Kiris birlesim minha kat-bazli",
         "Belirli katlarda KIRIS BIRLESIMLERI MINHA carpani."),
        ("kolon_head_minha_floor_scale",
         "Kolon basligi minha kat-bazli",
         "Belirli katlarda KOLON YERLERI MINHA carpani."),
    ]

    # ElementKind enum degerleri (UI dropdown icin)
    _ELEMENT_KINDS = [
        "column", "shear_wall", "beam", "slab", "slab_opening",
        "foundation", "lean_concrete", "parapet", "stair",
        "elevator_shaft", "chimney", "protection", "roof_slab",
    ]


    class FloorDictEditor(QWidget):  # type: ignore[misc]
        """Kat-bazli scale dict alanlari icin tablo editoru.

        Iki kolon: (Kat etiketi, Carpan). Kullanici satir ekleyip silebilir.
        ``to_dict()`` ile JSON-uyumlu dict doner; ``set_dict()`` ile yuklenir.
        """

        def __init__(self, parent: Optional[QWidget] = None) -> None:
            super().__init__(parent)
            lay = QVBoxLayout(self)

            # Field secici (hangi dict alanini duzenliyoruz)
            self.field_combo = QComboBox()
            for fname, label, _desc in _FLOOR_DICT_FIELDS:
                self.field_combo.addItem(label, fname)
            self.field_combo.currentIndexChanged.connect(self._on_field_changed)

            self.desc_label = QLabel()
            self.desc_label.setWordWrap(True)

            self.table = QTableWidget(0, 2)
            self.table.setHorizontalHeaderLabels(["Kat etiketi", "Carpan"])
            self.table.horizontalHeader().setStretchLastSection(True)
            self.table.horizontalHeader().setSectionResizeMode(
                QHeaderView.ResizeToContents,
            )

            btn_row = QHBoxLayout()
            add_btn = QPushButton("+ Satir Ekle")
            del_btn = QPushButton("- Satir Sil")
            add_btn.clicked.connect(self._add_row)
            del_btn.clicked.connect(self._del_row)
            btn_row.addWidget(add_btn)
            btn_row.addWidget(del_btn)
            btn_row.addStretch(1)

            lay.addWidget(QLabel("Hangi alani duzenliyorsun:"))
            lay.addWidget(self.field_combo)
            lay.addWidget(self.desc_label)
            lay.addWidget(self.table, 1)
            lay.addLayout(btn_row)

            self._dict_data: Dict[str, Dict[str, float]] = {
                fname: {} for fname, _, _ in _FLOOR_DICT_FIELDS
            }
            self._current_field: str = _FLOOR_DICT_FIELDS[0][0]
            self._on_field_changed()

        def _on_field_changed(self) -> None:
            # Onceki tabloyu kaydet
            self._save_table_to_dict()
            # Yeni alani yukle
            idx = self.field_combo.currentIndex()
            fname = self.field_combo.itemData(idx)
            self._current_field = fname
            # Aciklama guncelle
            for n, _l, desc in _FLOOR_DICT_FIELDS:
                if n == fname:
                    self.desc_label.setText(desc)
                    break
            # Tabloyu doldur
            self._load_dict_to_table(self._dict_data.get(fname, {}))

        def _add_row(self) -> None:
            r = self.table.rowCount()
            self.table.insertRow(r)
            self.table.setItem(r, 0, QTableWidgetItem(""))
            self.table.setItem(r, 1, QTableWidgetItem("1.0"))

        def _del_row(self) -> None:
            r = self.table.currentRow()
            if r >= 0:
                self.table.removeRow(r)

        def _save_table_to_dict(self) -> None:
            out: Dict[str, float] = {}
            for r in range(self.table.rowCount()):
                k_item = self.table.item(r, 0)
                v_item = self.table.item(r, 1)
                if not k_item or not v_item:
                    continue
                key = k_item.text().strip()
                if not key:
                    continue
                try:
                    val = float(v_item.text().strip())
                except (TypeError, ValueError):
                    continue
                out[key] = val
            if self._current_field:
                self._dict_data[self._current_field] = out

        def _load_dict_to_table(self, d: Dict[str, float]) -> None:
            self.table.setRowCount(0)
            for k, v in d.items():
                r = self.table.rowCount()
                self.table.insertRow(r)
                self.table.setItem(r, 0, QTableWidgetItem(str(k)))
                self.table.setItem(r, 1, QTableWidgetItem(str(v)))

        def to_dicts(self) -> Dict[str, Dict[str, float]]:
            """Tum dict alanlarini doner: {field_name: {floor: scale}}."""
            self._save_table_to_dict()
            return {k: dict(v) for k, v in self._dict_data.items() if v}

        def set_dicts(self, data: Dict[str, Dict[str, float]]) -> None:
            for fname in self._dict_data:
                self._dict_data[fname] = dict(data.get(fname, {}))
            # Mevcut alani yeniden yukle
            self._load_dict_to_table(self._dict_data.get(self._current_field, {}))


    class LayerOverrideEditor(QWidget):  # type: ignore[misc]
        """Katman ad → ElementKind override + dislama editoru.

        - `structural_layer_include_kind`: katman -> kind override
        - `structural_layer_exclude`: katman dislama listesi
        """

        def __init__(self, parent: Optional[QWidget] = None) -> None:
            super().__init__(parent)
            lay = QVBoxLayout(self)

            lay.addWidget(QLabel(
                "<b>Katman -> Yapisal Tur Override</b><br>"
                "Autodetect yanlis tani tanidigi katmanlari elle ayarla."
            ))

            self.include_table = QTableWidget(0, 2)
            self.include_table.setHorizontalHeaderLabels(["Katman adi", "ElementKind"])
            self.include_table.horizontalHeader().setStretchLastSection(True)
            self.include_table.horizontalHeader().setSectionResizeMode(
                QHeaderView.ResizeToContents,
            )

            inc_btns = QHBoxLayout()
            inc_add = QPushButton("+ Satir Ekle")
            inc_del = QPushButton("- Satir Sil")
            inc_add.clicked.connect(self._add_include_row)
            inc_del.clicked.connect(self._del_include_row)
            inc_btns.addWidget(inc_add)
            inc_btns.addWidget(inc_del)
            inc_btns.addStretch(1)

            lay.addWidget(self.include_table, 1)
            lay.addLayout(inc_btns)

            lay.addWidget(QLabel(
                "<b>Dislanan Katmanlar</b> (autodetect bulsa bile geometri cikarilmaz)"
            ))
            self.exclude_table = QTableWidget(0, 1)
            self.exclude_table.setHorizontalHeaderLabels(["Katman adi"])
            self.exclude_table.horizontalHeader().setStretchLastSection(True)

            exc_btns = QHBoxLayout()
            exc_add = QPushButton("+ Satir Ekle")
            exc_del = QPushButton("- Satir Sil")
            exc_add.clicked.connect(self._add_exclude_row)
            exc_del.clicked.connect(self._del_exclude_row)
            exc_btns.addWidget(exc_add)
            exc_btns.addWidget(exc_del)
            exc_btns.addStretch(1)

            lay.addWidget(self.exclude_table, 1)
            lay.addLayout(exc_btns)

        def _add_include_row(self) -> None:
            r = self.include_table.rowCount()
            self.include_table.insertRow(r)
            self.include_table.setItem(r, 0, QTableWidgetItem(""))
            combo = QComboBox()
            for k in _ELEMENT_KINDS:
                combo.addItem(k)
            self.include_table.setCellWidget(r, 1, combo)

        def _del_include_row(self) -> None:
            r = self.include_table.currentRow()
            if r >= 0:
                self.include_table.removeRow(r)

        def _add_exclude_row(self) -> None:
            r = self.exclude_table.rowCount()
            self.exclude_table.insertRow(r)
            self.exclude_table.setItem(r, 0, QTableWidgetItem(""))

        def _del_exclude_row(self) -> None:
            r = self.exclude_table.currentRow()
            if r >= 0:
                self.exclude_table.removeRow(r)

        def get_include_kind(self) -> Dict[str, str]:
            out: Dict[str, str] = {}
            for r in range(self.include_table.rowCount()):
                k = self.include_table.item(r, 0)
                w = self.include_table.cellWidget(r, 1)
                if not k or not isinstance(w, QComboBox):
                    continue
                layer = k.text().strip()
                if not layer:
                    continue
                out[layer] = w.currentText()
            return out

        def get_exclude_layers(self) -> List[str]:
            out: List[str] = []
            for r in range(self.exclude_table.rowCount()):
                k = self.exclude_table.item(r, 0)
                if not k:
                    continue
                lay = k.text().strip()
                if lay:
                    out.append(lay)
            return out

        def set_include_kind(self, mapping: Dict[str, str]) -> None:
            self.include_table.setRowCount(0)
            for layer, kind in mapping.items():
                r = self.include_table.rowCount()
                self.include_table.insertRow(r)
                self.include_table.setItem(r, 0, QTableWidgetItem(str(layer)))
                combo = QComboBox()
                for k in _ELEMENT_KINDS:
                    combo.addItem(k)
                if kind in _ELEMENT_KINDS:
                    combo.setCurrentText(kind)
                self.include_table.setCellWidget(r, 1, combo)

        def set_exclude_layers(self, layers: List[str]) -> None:
            self.exclude_table.setRowCount(0)
            for lay in layers:
                r = self.exclude_table.rowCount()
                self.exclude_table.insertRow(r)
                self.exclude_table.setItem(r, 0, QTableWidgetItem(str(lay)))


    class StructuralConfigDialog(QDialog):  # type: ignore[misc]
        """Excel-bagimsiz yapisal config sihirbazi (QDialog)."""

        def __init__(self, parent: Optional[QWidget] = None,
                     initial_preset: str = "geometry_full",
                     initial_output: Optional[Path] = None) -> None:
            super().__init__(parent)
            self.setWindowTitle("Yapisal Metraj Konfigurasyon Sihirbazi")
            self.setMinimumSize(720, 600)

            self._current_params = CalcParams()
            self._spin_widgets: Dict[str, QDoubleSpinBox] = {}

            main = QVBoxLayout(self)

            # Preset row
            preset_box = QGroupBox("Hazir Preset")
            preset_lay = QHBoxLayout(preset_box)
            self.preset_combo = QComboBox()
            for name in list_method_presets():
                self.preset_combo.addItem(name)
            if initial_preset in [self.preset_combo.itemText(i) for i in range(self.preset_combo.count())]:
                self.preset_combo.setCurrentText(initial_preset)
            preset_load_btn = QPushButton("Preset Yukle")
            preset_load_btn.clicked.connect(self._on_load_preset)
            preset_lay.addWidget(QLabel("Preset:"))
            preset_lay.addWidget(self.preset_combo, 1)
            preset_lay.addWidget(preset_load_btn)
            main.addWidget(preset_box)

            # Quick action buttons
            quick_box = QGroupBox("Hizli Ayarlar")
            quick_lay = QHBoxLayout(quick_box)
            full_btn = QPushButton("Saf Geometri (hepsi 1.0)")
            full_btn.clicked.connect(lambda: self._apply_quick_all(1.0))
            half_btn = QPushButton("Yari Kesit (hepsi 0.5)")
            half_btn.clicked.connect(lambda: self._apply_quick_all(0.5))
            quick_lay.addWidget(full_btn)
            quick_lay.addWidget(half_btn)
            quick_lay.addStretch(1)
            main.addWidget(quick_box)

            # Output yaml row
            out_box = QGroupBox("Cikti YAML")
            out_lay = QHBoxLayout(out_box)
            self.output_label = QLabel(str(initial_output) if initial_output else "profile.yaml")
            out_browse = QPushButton("Gozat...")
            out_browse.clicked.connect(self._pick_output)
            out_lay.addWidget(self.output_label, 1)
            out_lay.addWidget(out_browse)
            main.addWidget(out_box)

            # Tab widget: her FIELD_GROUPS bir tab
            self.tabs = QTabWidget()
            for group_name, fields in FIELD_GROUPS.items():
                page = QWidget()
                form = QFormLayout(page)
                for fdef in fields:
                    spin = QDoubleSpinBox()
                    spin.setRange(fdef.min_value, fdef.max_value)
                    spin.setDecimals(fdef.decimals)
                    spin.setSingleStep(fdef.step)
                    spin.setValue(float(getattr(self._current_params, fdef.name)))
                    if fdef.unit:
                        spin.setSuffix(f" {fdef.unit}")
                    spin.setToolTip(fdef.description)
                    form.addRow(QLabel(fdef.label + ":"), spin)
                    self._spin_widgets[fdef.name] = spin
                # Aciklama bolumu
                desc_text = "\n\n".join(
                    f"• {f.label}: {f.description}" for f in fields
                )
                desc = QTextEdit()
                desc.setReadOnly(True)
                desc.setPlainText(desc_text)
                desc.setMaximumHeight(120)
                form.addRow(QLabel(""))
                form.addRow(QLabel("Aciklama:"), desc)
                self.tabs.addTab(page, group_name)

            # Faz extra: kat-bazli dict ayarlari sekmesi
            self.floor_dict_editor = FloorDictEditor()
            self.tabs.addTab(self.floor_dict_editor, "Kat-bazli Ayarlar")

            # Faz extra: katman override sekmesi
            self.layer_override_editor = LayerOverrideEditor()
            self.tabs.addTab(self.layer_override_editor, "Katman Override")

            main.addWidget(self.tabs, 1)

            # Save / Cancel
            btn_box = QDialogButtonBox(
                QDialogButtonBox.Save | QDialogButtonBox.Cancel,
            )
            btn_box.accepted.connect(self._on_save)
            btn_box.rejected.connect(self.reject)
            main.addWidget(btn_box)

            # Ilk preset'i yukle
            self._on_load_preset()

        def _on_load_preset(self) -> None:
            name = self.preset_combo.currentText()
            try:
                self._current_params = load_method_preset(name)
            except FileNotFoundError as exc:
                QMessageBox.warning(self, "Preset", str(exc))
                return
            self._refresh_spins_from_params()

        def _refresh_spins_from_params(self) -> None:
            for name, spin in self._spin_widgets.items():
                val = getattr(self._current_params, name, None)
                if isinstance(val, (int, float)):
                    spin.setValue(float(val))
            # Kat-bazli dict alanlari da yukle
            if hasattr(self, "floor_dict_editor"):
                dict_data: Dict[str, Dict[str, float]] = {}
                for fname, _l, _d in _FLOOR_DICT_FIELDS:
                    val = getattr(self._current_params, fname, None)
                    if isinstance(val, dict):
                        dict_data[fname] = {str(k): float(v) for k, v in val.items()}
                self.floor_dict_editor.set_dicts(dict_data)

        def _apply_quick_all(self, value: float) -> None:
            """Tum scale/fraction alanlarini tek degere set et."""
            for name, spin in self._spin_widgets.items():
                # Sadece "fraction"/"scale" iceren alanlari etkile, fiziksel
                # boyutlari (m) degistirme.
                if any(k in name for k in ("fraction", "scale")):
                    spin.setValue(value)

        def _pick_output(self) -> None:
            current = self.output_label.text() or "profile.yaml"
            path, _ = QFileDialog.getSaveFileName(
                self, "Cikti YAML kaydet", current, "YAML (*.yaml *.yml)",
            )
            if path:
                self.output_label.setText(path)

        def _collect_params_from_spins(self) -> CalcParams:
            cp = CalcParams(**asdict(self._current_params))
            for name, spin in self._spin_widgets.items():
                try:
                    setattr(cp, name, float(spin.value()))
                except Exception:
                    pass
            # Kat-bazli dict alanlarini da topla
            if hasattr(self, "floor_dict_editor"):
                for fname, scales in self.floor_dict_editor.to_dicts().items():
                    if hasattr(cp, fname):
                        try:
                            setattr(cp, fname, dict(scales))
                        except Exception:
                            pass
            return cp

        def _on_save(self) -> None:
            out_path = Path(self.output_label.text().strip())
            if not out_path or out_path == Path():
                QMessageBox.warning(self, "Cikti", "Cikti YAML yolu bos.")
                return
            cp = self._collect_params_from_spins()
            inc_kind: Dict[str, str] = {}
            exc_layers: List[str] = []
            if hasattr(self, "layer_override_editor"):
                inc_kind = self.layer_override_editor.get_include_kind()
                exc_layers = self.layer_override_editor.get_exclude_layers()
            try:
                calcparams_to_yaml(
                    cp, out_path,
                    project_name=f"Custom ({self.preset_combo.currentText()})",
                    excel_layout="generic",
                    structural_layer_include_kind=inc_kind,
                    structural_layer_exclude=exc_layers,
                )
                QMessageBox.information(
                    self, "Kaydedildi",
                    f"Profil YAML kaydedildi:\n{out_path.resolve()}\n\n"
                    f"Sonraki adim:\n"
                    f"  metraj run --mode structural \\\n"
                    f"    --structural-config {out_path} <cad>",
                )
                self.accept()
            except Exception as exc:
                QMessageBox.critical(self, "Kayit hatasi", str(exc))


def launch_config_dialog(
    preset: str = "geometry_full",
    output: Optional[Path] = None,
) -> int:
    """CLI'den dialog'u acar. Return: 0 = kaydedildi, 1 = iptal."""
    if not PYSIDE_AVAILABLE:
        raise RuntimeError("PySide6 yuklu degil. Kurulum: pip install PySide6")
    app = QApplication.instance() or QApplication(sys.argv)
    dlg = StructuralConfigDialog(initial_preset=preset, initial_output=output)
    if dlg.exec() == QDialog.Accepted:
        return 0
    return 1


__all__ = [
    "FIELD_GROUPS",
    "FieldDef",
    "PYSIDE_AVAILABLE",
    "calcparams_to_yaml",
    "field_groups_to_flat_list",
    "launch_config_dialog",
    "list_method_presets",
    "load_method_preset",
]
