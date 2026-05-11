"""Faz 4 GUI: PySide6 kalibrasyon sihirbazi.

CLI ``metraj structural-fit`` iş akisini gorsel bir QDialog'a sariyor:

  1. Dosya secimi: CAD + Referans Excel + cikti YAML
  2. Profile fit (background QThread, profile_fitter.fit_profile_from_dxf)
  3. Sonuc tablosu — kullanici scale alanlarini manuel ince ayar yapabilir
  4. "Test et" — fitted params ile pipeline kosturulur, KALIP/BETON sapma
  5. Kaydet — dump_fitted_yaml ile YAML cikar

PySide6 yoksa modul import sirasinda ``PYSIDE_AVAILABLE = False`` olur ve
``launch_wizard`` bir RuntimeError doner.
"""
from __future__ import annotations

import logging
import sys
import traceback
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    from PySide6.QtCore import Qt, QThread, Signal
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
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
        QMessageBox,
        QProgressBar,
        QPushButton,
        QStackedWidget,
        QTableWidget,
        QTableWidgetItem,
        QTextEdit,
        QVBoxLayout,
        QWidget,
    )

    PYSIDE_AVAILABLE = True
except ImportError:  # pragma: no cover
    PYSIDE_AVAILABLE = False


from ..core.structural.calculator import CalcParams
from ..core.structural.config import StructuralConfig
from ..core.structural.profile_fitter import (
    FitResult,
    dump_fitted_yaml,
    fit_profile_from_dxf,
)


# ---------------------------------------------------------------------------
# Non-GUI helper'lar — test edilebilir
# ---------------------------------------------------------------------------


def apply_user_edits_to_params(
    base_params: CalcParams,
    edits: Dict[str, float],
) -> CalcParams:
    """Kullanicinin tabloda yaptigi duzenlemeyi CalcParams uzerine uygular.

    ``edits``: ``{field_name: new_value}``. Mevcut olmayan veya non-float
    alanlar sessizce atlanir.
    """
    out = CalcParams(**asdict(base_params))
    for name, val in edits.items():
        if not hasattr(out, name):
            continue
        try:
            setattr(out, name, float(val))
        except (TypeError, ValueError):
            logger.warning("Wizard edit gecersiz: %s=%r", name, val)
    return out


def collect_editable_fields(fit_result: FitResult) -> List[Dict[str, Any]]:
    """``FitResult``'ten kullanici tablosu icin satir veri yapisi uretir.

    Her satir: ``{field_name, fitted_value, baseline_total, reference_total,
    matched_rows}`` — wizard table widget'i bunu doldurur.
    """
    rows: List[Dict[str, Any]] = []
    for fr in fit_result.field_results:
        rows.append({
            "field_name": fr.field_name,
            "fitted_value": float(fr.fitted_value),
            "baseline_total": float(fr.baseline_total),
            "reference_total": float(fr.reference_total),
            "matched_rows": int(fr.matched_rows),
        })
    return rows


# ---------------------------------------------------------------------------
# GUI (PySide6 varsa)
# ---------------------------------------------------------------------------


if PYSIDE_AVAILABLE:

    class _FitWorker(QThread):  # type: ignore[misc]
        finished_ok = Signal(object)        # FitResult
        finished_err = Signal(str)
        progress_msg = Signal(str)

        def __init__(self, cad_path: Path, ref_path: Path) -> None:
            super().__init__()
            self._cad = cad_path
            self._ref = ref_path

        def run(self) -> None:  # noqa: D401
            try:
                self.progress_msg.emit("Saf geometri pipeline'i kosturuluyor...")
                res = fit_profile_from_dxf(
                    cad_path=self._cad,
                    reference_excel=self._ref,
                    output_yaml=None,
                    two_stage_fit=True,
                )
                self.finished_ok.emit(res)
            except Exception as exc:  # pragma: no cover
                logger.exception("FitWorker hatasi")
                self.finished_err.emit(f"{exc}\n{traceback.format_exc()}")

    class _TestWorker(QThread):  # type: ignore[misc]
        """Fitted params ile pipeline'i kostur, sapma metrikleri."""

        finished_ok = Signal(dict)
        finished_err = Signal(str)

        def __init__(self, cad_path: Path, ref_path: Path, params: CalcParams) -> None:
            super().__init__()
            self._cad = cad_path
            self._ref = ref_path
            self._params = params

        def run(self) -> None:  # noqa: D401
            try:
                from ..core.structural.pipeline import StructuralPipeline
                from ..core.structural.gt_io import parse_kumluca_reference
                cfg = StructuralConfig(
                    project_name="Wizard-Test",
                    params=self._params,
                    reference_excel_path=str(self._ref),
                    excel_layout="kumluca",
                    compare_to_reference=True,
                    validation_tolerance=0.01,
                )
                pipe = StructuralPipeline(config=cfg)
                res = pipe.run(cad_path=self._cad,
                               output_dir="build/_wizard_test",
                               write_excel=False, write_diagnostics=False)
                ref_rep = parse_kumluca_reference(self._ref)
                ref_form = sum(r.total for r in ref_rep.formwork_rows)
                ref_conc = sum(r.total for r in ref_rep.concrete_rows)
                f_total = float(res.report.formwork_total_m2)
                c_total = float(res.report.concrete_total_m3)
                f_dev = abs(f_total - ref_form) / max(abs(ref_form), 1e-9)
                c_dev = abs(c_total - ref_conc) / max(abs(ref_conc), 1e-9)
                max_k = (res.validation_detail.max_rel_error_formwork
                         if res.validation_detail else 0.0)
                max_b = (res.validation_detail.max_rel_error_concrete
                         if res.validation_detail else 0.0)
                self.finished_ok.emit({
                    "computed_form_m2": f_total,
                    "computed_conc_m3": c_total,
                    "ref_form_m2": ref_form,
                    "ref_conc_m3": ref_conc,
                    "form_total_dev": f_dev,
                    "conc_total_dev": c_dev,
                    "max_row_form_dev": max_k,
                    "max_row_conc_dev": max_b,
                })
            except Exception as exc:  # pragma: no cover
                logger.exception("TestWorker hatasi")
                self.finished_err.emit(f"{exc}\n{traceback.format_exc()}")

    class CalibrationWizard(QDialog):  # type: ignore[misc]
        """5 adimli kalibrasyon sihirbazi."""

        STEP_FILES = 0
        STEP_FIT = 1
        STEP_EDIT = 2
        STEP_TEST = 3
        STEP_SAVE = 4

        def __init__(self, parent: Optional[QWidget] = None,
                     initial_cad: Optional[Path] = None,
                     initial_ref: Optional[Path] = None,
                     initial_output: Optional[Path] = None) -> None:
            super().__init__(parent)
            self.setWindowTitle("Metraj Kalibrasyon Sihirbazi (Faz 4)")
            self.setMinimumSize(820, 560)

            self._fit_result: Optional[FitResult] = None
            self._edited_params: Optional[CalcParams] = None
            self._fit_worker: Optional[_FitWorker] = None
            self._test_worker: Optional[_TestWorker] = None

            self._stack = QStackedWidget(self)
            self._step_label = QLabel(self)
            font = QFont()
            font.setBold(True)
            font.setPointSize(11)
            self._step_label.setFont(font)

            self._prev_btn = QPushButton("< Onceki", self)
            self._next_btn = QPushButton("Sonraki >", self)
            self._cancel_btn = QPushButton("Iptal", self)
            self._prev_btn.clicked.connect(self._on_prev)
            self._next_btn.clicked.connect(self._on_next)
            self._cancel_btn.clicked.connect(self.reject)

            btn_row = QHBoxLayout()
            btn_row.addStretch(1)
            btn_row.addWidget(self._prev_btn)
            btn_row.addWidget(self._next_btn)
            btn_row.addWidget(self._cancel_btn)

            main = QVBoxLayout(self)
            main.addWidget(self._step_label)
            main.addWidget(self._stack, 1)
            main.addLayout(btn_row)

            self._build_step_files(initial_cad, initial_ref, initial_output)
            self._build_step_fit()
            self._build_step_edit()
            self._build_step_test()
            self._build_step_save()

            self._stack.setCurrentIndex(self.STEP_FILES)
            self._update_buttons()

        # ----- Adim 1: Dosya secimi -------------------------------------
        def _build_step_files(self, cad, ref, out) -> None:
            page = QWidget()
            f = QFormLayout(page)

            self.cad_edit = QLineEdit(str(cad) if cad else "")
            cad_btn = QPushButton("Gozat...")
            cad_btn.clicked.connect(lambda: self._pick_file(
                self.cad_edit, "CAD dosyasi sec",
                "AutoCAD dosyalari (*.dwg *.dxf)"))
            cad_row = QHBoxLayout()
            cad_row.addWidget(self.cad_edit, 1)
            cad_row.addWidget(cad_btn)
            f.addRow(QLabel("CAD (DWG/DXF):"), self._wrap_layout(cad_row))

            self.ref_edit = QLineEdit(str(ref) if ref else "")
            ref_btn = QPushButton("Gozat...")
            ref_btn.clicked.connect(lambda: self._pick_file(
                self.ref_edit, "Referans Excel sec",
                "Excel (*.xlsx *.xls)"))
            ref_row = QHBoxLayout()
            ref_row.addWidget(self.ref_edit, 1)
            ref_row.addWidget(ref_btn)
            f.addRow(QLabel("Referans Excel:"), self._wrap_layout(ref_row))

            self.out_edit = QLineEdit(str(out) if out else "profile.yaml")
            out_btn = QPushButton("Gozat...")
            out_btn.clicked.connect(lambda: self._pick_save(
                self.out_edit, "Cikti YAML",
                "YAML (*.yaml *.yml)"))
            out_row = QHBoxLayout()
            out_row.addWidget(self.out_edit, 1)
            out_row.addWidget(out_btn)
            f.addRow(QLabel("Cikti YAML:"), self._wrap_layout(out_row))

            info = QLabel(
                "Bu sihirbaz CAD + Referans Excel'den otomatik bir "
                "<b>CalcParams profili</b> uretir.<br>"
                "Sonraki adimda saf geometri pipeline'i koshturulup ana scale "
                "alanlari fit edilecek (yaklasik 10-20 saniye)."
            )
            info.setWordWrap(True)
            f.addRow(info)

            self._stack.addWidget(page)

        # ----- Adim 2: Fit ----------------------------------------------
        def _build_step_fit(self) -> None:
            page = QWidget()
            lay = QVBoxLayout(page)
            self.fit_status = QLabel("Hazir.")
            self.fit_progress = QProgressBar()
            self.fit_progress.setRange(0, 0)  # belirsiz
            self.fit_progress.hide()
            self.fit_log = QTextEdit()
            self.fit_log.setReadOnly(True)
            font = QFont("Courier")
            self.fit_log.setFont(font)
            lay.addWidget(QLabel("Profile fit ilerlemesi:"))
            lay.addWidget(self.fit_status)
            lay.addWidget(self.fit_progress)
            lay.addWidget(self.fit_log, 1)
            self._stack.addWidget(page)

        # ----- Adim 3: Edit ---------------------------------------------
        def _build_step_edit(self) -> None:
            page = QWidget()
            lay = QVBoxLayout(page)
            lay.addWidget(QLabel(
                "Otomatik fit edilen scale degerleri. <b>Manuel ince ayar</b> "
                "yapmak istiyorsaniz tablodaki sayilari duzenleyin."
            ))
            self.edit_table = QTableWidget()
            self.edit_table.setColumnCount(5)
            self.edit_table.setHorizontalHeaderLabels(
                ["CalcParams alani", "Fitted scale", "Baseline toplam",
                 "Referans toplam", "Satir sayisi"]
            )
            self.edit_table.horizontalHeader().setSectionResizeMode(
                QHeaderView.ResizeToContents,
            )
            self.edit_table.horizontalHeader().setStretchLastSection(True)
            lay.addWidget(self.edit_table, 1)
            self._stack.addWidget(page)

        # ----- Adim 4: Test ---------------------------------------------
        def _build_step_test(self) -> None:
            page = QWidget()
            lay = QVBoxLayout(page)
            lay.addWidget(QLabel(
                "Fit edilen profil ile pipeline'i kostur, referansa karsi "
                "sapmayi gor."
            ))
            self.test_btn = QPushButton("Pipeline test koshtur")
            self.test_btn.clicked.connect(self._on_test_run)
            lay.addWidget(self.test_btn)
            self.test_progress = QProgressBar()
            self.test_progress.setRange(0, 0)
            self.test_progress.hide()
            lay.addWidget(self.test_progress)

            self.test_result_box = QGroupBox("Sapma metrikleri")
            ml = QFormLayout(self.test_result_box)
            self.test_form_total = QLabel("—")
            self.test_conc_total = QLabel("—")
            self.test_form_dev = QLabel("—")
            self.test_conc_dev = QLabel("—")
            self.test_max_row_form = QLabel("—")
            self.test_max_row_conc = QLabel("—")
            ml.addRow("KALIP toplam (m²):", self.test_form_total)
            ml.addRow("BETON toplam (m³):", self.test_conc_total)
            ml.addRow("KALIP toplam sapma:", self.test_form_dev)
            ml.addRow("BETON toplam sapma:", self.test_conc_dev)
            ml.addRow("Satir-bazi MAX KALIP sapma:", self.test_max_row_form)
            ml.addRow("Satir-bazi MAX BETON sapma:", self.test_max_row_conc)
            self.test_result_box.setEnabled(False)
            lay.addWidget(self.test_result_box)
            lay.addStretch(1)
            self._stack.addWidget(page)

        # ----- Adim 5: Save ---------------------------------------------
        def _build_step_save(self) -> None:
            page = QWidget()
            lay = QVBoxLayout(page)
            lay.addWidget(QLabel(
                "Son adim: profil YAML olarak diske kaydedilecek."
            ))
            self.save_summary = QTextEdit()
            self.save_summary.setReadOnly(True)
            self.save_summary.setFont(QFont("Courier"))
            lay.addWidget(self.save_summary, 1)
            self._stack.addWidget(page)

        # ----- Navigation -----------------------------------------------
        def _wrap_layout(self, lay) -> QWidget:
            w = QWidget()
            w.setLayout(lay)
            return w

        def _pick_file(self, edit: QLineEdit, title: str, flt: str) -> None:
            current = edit.text() or str(Path.cwd())
            path, _ = QFileDialog.getOpenFileName(self, title, current, flt)
            if path:
                edit.setText(path)

        def _pick_save(self, edit: QLineEdit, title: str, flt: str) -> None:
            current = edit.text() or str(Path.cwd() / "profile.yaml")
            path, _ = QFileDialog.getSaveFileName(self, title, current, flt)
            if path:
                edit.setText(path)

        def _update_buttons(self) -> None:
            idx = self._stack.currentIndex()
            step_titles = [
                "Adim 1/5: Dosya secimi",
                "Adim 2/5: Profil fit",
                "Adim 3/5: Manuel ince ayar",
                "Adim 4/5: Test koshtur",
                "Adim 5/5: Kaydet",
            ]
            self._step_label.setText(step_titles[idx])
            self._prev_btn.setEnabled(idx > self.STEP_FILES)
            # Son adimda "Sonraki" yerine "Kaydet ve Kapat"
            if idx == self.STEP_SAVE:
                self._next_btn.setText("Kaydet ve Kapat")
            else:
                self._next_btn.setText("Sonraki >")

        def _on_prev(self) -> None:
            idx = self._stack.currentIndex()
            if idx > self.STEP_FILES:
                self._stack.setCurrentIndex(idx - 1)
                self._update_buttons()

        def _on_next(self) -> None:
            idx = self._stack.currentIndex()
            if idx == self.STEP_FILES:
                if not self._validate_files():
                    return
                self._stack.setCurrentIndex(self.STEP_FIT)
                self._update_buttons()
                self._start_fit()
                return
            if idx == self.STEP_FIT:
                if self._fit_result is None:
                    QMessageBox.information(
                        self, "Bekleyin", "Fit hala calisiyor veya henuz tamamlanmadi."
                    )
                    return
                self._stack.setCurrentIndex(self.STEP_EDIT)
                self._update_buttons()
                self._populate_edit_table()
                return
            if idx == self.STEP_EDIT:
                self._collect_edits()
                self._stack.setCurrentIndex(self.STEP_TEST)
                self._update_buttons()
                return
            if idx == self.STEP_TEST:
                self._stack.setCurrentIndex(self.STEP_SAVE)
                self._update_buttons()
                self._populate_save_summary()
                return
            if idx == self.STEP_SAVE:
                self._save_and_close()
                return

        def _validate_files(self) -> bool:
            cad = Path(self.cad_edit.text().strip())
            ref = Path(self.ref_edit.text().strip())
            out = Path(self.out_edit.text().strip())
            if not cad.is_file():
                QMessageBox.warning(self, "Eksik", f"CAD bulunamadi: {cad}")
                return False
            if not ref.is_file():
                QMessageBox.warning(self, "Eksik", f"Referans Excel bulunamadi: {ref}")
                return False
            if not str(out).strip():
                QMessageBox.warning(self, "Eksik", "Cikti YAML yolu bos.")
                return False
            return True

        # ----- Fit worker -----------------------------------------------
        def _start_fit(self) -> None:
            cad = Path(self.cad_edit.text().strip())
            ref = Path(self.ref_edit.text().strip())
            self.fit_status.setText("Fit calisiyor...")
            self.fit_progress.show()
            self.fit_log.clear()
            self.fit_log.append(f"CAD: {cad}")
            self.fit_log.append(f"Referans: {ref}")
            self._fit_worker = _FitWorker(cad, ref)
            self._fit_worker.progress_msg.connect(
                lambda m: self.fit_log.append(m)
            )
            self._fit_worker.finished_ok.connect(self._on_fit_ok)
            self._fit_worker.finished_err.connect(self._on_fit_err)
            self._fit_worker.start()

        def _on_fit_ok(self, result) -> None:
            self._fit_result = result
            self.fit_progress.hide()
            self.fit_status.setText("Fit tamamlandi. 'Sonraki' ile ilerleyin.")
            self.fit_log.append("")
            self.fit_log.append(result.report)

        def _on_fit_err(self, msg: str) -> None:
            self.fit_progress.hide()
            self.fit_status.setText("Fit basarisiz oldu.")
            self.fit_log.append("HATA: " + msg)
            QMessageBox.critical(self, "Fit hatasi", msg)

        # ----- Edit table -----------------------------------------------
        def _populate_edit_table(self) -> None:
            if self._fit_result is None:
                return
            rows = collect_editable_fields(self._fit_result)
            self.edit_table.setRowCount(len(rows))
            for i, r in enumerate(rows):
                self.edit_table.setItem(i, 0, QTableWidgetItem(r["field_name"]))
                spin = QDoubleSpinBox()
                spin.setRange(0.0, 100.0)
                spin.setDecimals(4)
                spin.setSingleStep(0.01)
                spin.setValue(r["fitted_value"])
                self.edit_table.setCellWidget(i, 1, spin)
                self.edit_table.setItem(i, 2, QTableWidgetItem(
                    f"{r['baseline_total']:.2f}"))
                self.edit_table.setItem(i, 3, QTableWidgetItem(
                    f"{r['reference_total']:.2f}"))
                self.edit_table.setItem(i, 4, QTableWidgetItem(
                    str(r["matched_rows"])))

        def _collect_edits(self) -> None:
            """Tablodan duzenlenen scale degerlerini topla, _edited_params'a uygula."""
            if self._fit_result is None:
                return
            edits: Dict[str, float] = {}
            for i in range(self.edit_table.rowCount()):
                item = self.edit_table.item(i, 0)
                spin = self.edit_table.cellWidget(i, 1)
                if not item or spin is None:
                    continue
                name = item.text()
                edits[name] = float(spin.value())
            self._edited_params = apply_user_edits_to_params(
                self._fit_result.fitted_params, edits,
            )

        # ----- Test worker ---------------------------------------------
        def _on_test_run(self) -> None:
            if self._edited_params is None:
                self._collect_edits()
            params = self._edited_params or (
                self._fit_result.fitted_params if self._fit_result else None
            )
            if params is None:
                QMessageBox.warning(self, "Eksik", "Fit sonucu yok; once Adim 2'yi tamamlayin.")
                return
            self.test_btn.setEnabled(False)
            self.test_progress.show()
            cad = Path(self.cad_edit.text().strip())
            ref = Path(self.ref_edit.text().strip())
            self._test_worker = _TestWorker(cad, ref, params)
            self._test_worker.finished_ok.connect(self._on_test_ok)
            self._test_worker.finished_err.connect(self._on_test_err)
            self._test_worker.start()

        def _on_test_ok(self, metrics: dict) -> None:
            self.test_progress.hide()
            self.test_btn.setEnabled(True)
            self.test_form_total.setText(f"{metrics['computed_form_m2']:.2f}")
            self.test_conc_total.setText(f"{metrics['computed_conc_m3']:.2f}")
            self.test_form_dev.setText(f"{metrics['form_total_dev']*100:.2f}%")
            self.test_conc_dev.setText(f"{metrics['conc_total_dev']*100:.2f}%")
            self.test_max_row_form.setText(f"{metrics['max_row_form_dev']*100:.2f}%")
            self.test_max_row_conc.setText(f"{metrics['max_row_conc_dev']*100:.2f}%")
            self.test_result_box.setEnabled(True)

        def _on_test_err(self, msg: str) -> None:
            self.test_progress.hide()
            self.test_btn.setEnabled(True)
            QMessageBox.critical(self, "Test hatasi", msg)

        # ----- Save -----------------------------------------------------
        def _populate_save_summary(self) -> None:
            self._collect_edits()
            cp = self._edited_params or (
                self._fit_result.fitted_params if self._fit_result else CalcParams()
            )
            lines = ["# Kayit ediliyor: CalcParams"]
            for fld in cp.__dataclass_fields__:
                val = getattr(cp, fld)
                if isinstance(val, dict):
                    if val:
                        lines.append(f"{fld}:")
                        for k, v in val.items():
                            lines.append(f"  {k}: {v}")
                elif isinstance(val, (int, float)):
                    default = getattr(CalcParams(), fld)
                    if val != default:
                        lines.append(f"{fld}: {val}")
            lines.append("")
            lines.append(f"Cikti YAML: {self.out_edit.text()}")
            self.save_summary.setPlainText("\n".join(lines))

        def _save_and_close(self) -> None:
            self._collect_edits()
            cp = self._edited_params or (
                self._fit_result.fitted_params if self._fit_result else CalcParams()
            )
            out_path = Path(self.out_edit.text().strip())
            try:
                ref = Path(self.ref_edit.text().strip())
                try:
                    ref_rel = str(ref.resolve().relative_to(out_path.parent.resolve()))
                except ValueError:
                    ref_rel = str(ref.resolve())
                dump_fitted_yaml(
                    cp, out_path,
                    project_name=f"Wizard ({Path(self.cad_edit.text()).stem})",
                    reference_excel_relative=ref_rel,
                )
                QMessageBox.information(
                    self, "Kaydedildi",
                    f"Profil YAML kaydedildi:\n{out_path.resolve()}",
                )
                self.accept()
            except Exception as exc:
                QMessageBox.critical(self, "Kayit hatasi", str(exc))


def launch_wizard(
    cad: Optional[Path] = None,
    ref: Optional[Path] = None,
    output: Optional[Path] = None,
) -> int:
    """Standalone CLI'den sihirbazi acar. Donus: QDialog exit code."""
    if not PYSIDE_AVAILABLE:
        raise RuntimeError(
            "PySide6 yuklu degil. Kurulum: pip install PySide6"
        )
    app = QApplication.instance() or QApplication(sys.argv)
    wiz = CalibrationWizard(
        initial_cad=cad, initial_ref=ref, initial_output=output,
    )
    if wiz.exec() == QDialog.Accepted:
        return 0
    return 1


__all__ = [
    "apply_user_edits_to_params",
    "collect_editable_fields",
    "launch_wizard",
    "PYSIDE_AVAILABLE",
]
