"""PySide6 main window scaffold.

Provides a usable but intentionally minimal UI:

* File picker for DWG/DXF input
* Output folder picker
* Run button (invokes :class:`Pipeline`)
* Tabs:
    - Mahal listesi (QTableView)
    - Acikliklar (QTableView)
    - Icmal (QTableView)
    - 2D Plan goruntuleyici (QGraphicsView, reads the same model)
    - Uyarilar (QListWidget)

PyQt/PySide are not required to import the rest of the package; the import is
done lazily.
"""
from __future__ import annotations

import logging
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, get_args

logger = logging.getLogger(__name__)

try:
    from PySide6.QtCore import QPointF, QRectF, Qt, QThread, QUrl, Signal
    from PySide6.QtGui import (
        QAction,
        QBrush,
        QColor,
        QDesktopServices,
        QPainter,
        QPen,
        QPolygonF,
    )
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QComboBox,
        QDialog,
        QDialogButtonBox,
        QFileDialog,
        QGraphicsItem,
        QGraphicsScene,
        QGraphicsView,
        QHBoxLayout,
        QLabel,
        QListWidget,
        QMainWindow,
        QMessageBox,
        QPushButton,
        QStatusBar,
        QTableWidget,
        QTableWidgetItem,
        QTabWidget,
        QTextBrowser,
        QVBoxLayout,
        QWidget,
        QDoubleSpinBox,
    )

    PYSIDE_AVAILABLE = True
except ImportError:
    PYSIDE_AVAILABLE = False


from ..core.cad_io.converter import OdaNotFoundError, diagnose_dwg_support
from ..core.structural import (
    StructuralConfig,
    StructuralPipeline,
    StructuralPipelineResult,
    default_config as default_structural_config,
)
from ..core.structural.elements import ElementKind
from ..pipeline import Pipeline, PipelineConfig, PipelineResult


def launch(config_dir: Path) -> int:
    if not PYSIDE_AVAILABLE:
        print("PySide6 yuklu degil. Kurulum: pip install PySide6", file=sys.stderr)
        return 2
    app = QApplication.instance() or QApplication(sys.argv)
    config = PipelineConfig.from_directory(config_dir)
    window = MainWindow(config)
    window.show()
    return app.exec()


if PYSIDE_AVAILABLE:

    class PipelineWorker(QThread):  # type: ignore[misc]
        finished_ok = Signal(object)            # PipelineResult (mimari)
        finished_struct = Signal(object)        # StructuralPipelineResult
        finished_err = Signal(str, str)         # error_kind, message

        def __init__(self,
                     arch_pipeline: Pipeline,
                     struct_pipeline: StructuralPipeline,
                     cad_path: Path,
                     output_dir: Path,
                     oda_binary: Optional[str],
                     mode: str = "auto") -> None:
            super().__init__()
            self._arch = arch_pipeline
            self._struct = struct_pipeline
            self._cad_path = cad_path
            self._output_dir = output_dir
            self._oda_binary = oda_binary
            self._mode = mode

        def run(self) -> None:  # noqa: D401 - QThread override
            try:
                mode = self._mode
                if mode == "auto":
                    # CAD dosyasini bir kerelik okuyup mod kararini ver
                    from ..core.cad_io import DwgConverter, DxfReader
                    conv = DwgConverter(binary_path=self._oda_binary)
                    dxf_path = conv.ensure_dxf(self._cad_path)
                    model = DxfReader().read(dxf_path)
                    mode = detect_drawing_kind(model)
                if mode == "structural":
                    result = self._struct.run(
                        cad_path=self._cad_path,
                        output_dir=self._output_dir,
                    )
                    self.finished_struct.emit(result)
                else:
                    result = self._arch.run(
                        cad_path=self._cad_path,
                        output_dir=self._output_dir,
                        oda_binary=self._oda_binary,
                    )
                    self.finished_ok.emit(result)
            except OdaNotFoundError as exc:
                self.finished_err.emit("oda_not_found", str(exc))
            except RuntimeError as exc:
                msg = str(exc)
                kind = "oda_not_found" if "ODA" in msg else "runtime"
                self.finished_err.emit(kind, msg)
            except Exception as exc:
                logger.exception("Pipeline calisirken hata")
                self.finished_err.emit("runtime", str(exc))


    class OdaInstallDialog(QDialog):  # type: ignore[misc]
        """ODA File Converter eksikse kullaniciyi yonlendiren rehber dialog."""

        def __init__(self, parent: Optional[QWidget] = None) -> None:
            super().__init__(parent)
            self.setWindowTitle("ODA File Converter Gerekli")
            self.setMinimumSize(620, 480)
            info = diagnose_dwg_support()
            layout = QVBoxLayout(self)

            header = QLabel(
                "<h2 style='color:#1F3864'>DWG dosyasini okumak icin bir kerelik kurulum gerekiyor</h2>"
                "<p>Sistem AutoCAD'in ikili DWG formatini kendisi okuyamaz.  "
                "Bunun icin <b>ODA File Converter</b> (ucretsiz) gerekli; ya da "
                "elinizdeki dosyayi <b>DXF</b> olarak kaydederseniz hicbir kuruluma gerek kalmaz.</p>"
            )
            header.setWordWrap(True)
            header.setTextFormat(Qt.RichText)
            layout.addWidget(header)

            instructions = QTextBrowser()
            instructions.setOpenExternalLinks(True)
            install_html = info["install_help"].replace("\n", "<br/>")
            instructions.setHtml(
                f"<div style='font-family:monospace; font-size:11pt; "
                f"background:#F2F2F2; padding:10px;'>{install_html}</div>"
                f"<p><b>Indirme baglantisi:</b><br/>"
                f"<a href='{info['download_url']}'>{info['download_url']}</a></p>"
                f"<p><i>Platform: {info['platform']} {info['platform_release']}</i></p>"
            )
            layout.addWidget(instructions)

            button_row = QHBoxLayout()
            download_btn = QPushButton("Indirme Sayfasini Ac")
            download_btn.clicked.connect(
                lambda: QDesktopServices.openUrl(QUrl(info["download_url"]))
            )
            button_row.addWidget(download_btn)
            recheck_btn = QPushButton("Kurulumu Yeniden Kontrol Et")
            recheck_btn.clicked.connect(self._recheck)
            button_row.addWidget(recheck_btn)
            close_btn = QPushButton("Kapat")
            close_btn.clicked.connect(self.accept)
            button_row.addWidget(close_btn)
            layout.addLayout(button_row)

            self._recheck_label = QLabel("")
            self._recheck_label.setWordWrap(True)
            layout.addWidget(self._recheck_label)

        def _recheck(self) -> None:
            info = diagnose_dwg_support()
            if info["oda_available"]:
                self._recheck_label.setText(
                    f"<span style='color:green'><b>Bulundu:</b> {info['oda_path']}<br/>"
                    f"Pencereyi kapatip 'Metraji Calistir' butonunu tekrar deneyin.</span>"
                )
            else:
                self._recheck_label.setText(
                    "<span style='color:#C00'>Henuz bulunamadi. Kurulumdan sonra "
                    "uygulamayi <b>tamamen kapatip</b> yeniden acmaniz gerekebilir.</span>"
                )

    class PlanView(QGraphicsView):  # type: ignore[misc]
        """Lightweight 2D plan viewer.

        Renders walls (black lines), rooms (filled translucent polygons),
        room labels and openings (red markers).
        """

        def __init__(self) -> None:
            super().__init__()
            self._scene = QGraphicsScene(self)
            self.setScene(self._scene)
            self.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
            self.setDragMode(QGraphicsView.ScrollHandDrag)

        def render_result(self, result: PipelineResult) -> None:
            self._scene.clear()
            wall_pen = QPen(QColor(20, 20, 20))
            wall_pen.setWidthF(0.05)
            for line in result.model.lines:
                role = result.model  # for symmetry with future role-based coloring
                self._scene.addLine(
                    line.start[0], -line.start[1], line.end[0], -line.end[1], wall_pen,
                )
            for poly in result.model.polylines:
                pts = [QPointF(x, -y) for (x, y) in poly.points]
                if poly.closed and pts and pts[0] != pts[-1]:
                    pts.append(pts[0])
                qp = QPolygonF(pts)
                self._scene.addPolygon(qp, QPen(QColor(80, 80, 80), 0.05))
            room_brush = QBrush(QColor(80, 140, 220, 60))
            room_pen = QPen(QColor(50, 100, 180), 0.05)
            for room in result.rooms:
                xs, ys = zip(*room.polygon.exterior.coords)
                qp = QPolygonF([QPointF(x, -y) for x, y in zip(xs, ys)])
                self._scene.addPolygon(qp, room_pen, room_brush)
                cx = sum(xs) / len(xs)
                cy = sum(ys) / len(ys)
                text_item = self._scene.addText(f"{room.code}\n{room.name}")
                text_item.setDefaultTextColor(QColor(30, 30, 80))
                text_item.setPos(cx, -cy)
            opening_pen = QPen(QColor(200, 30, 30), 0.1)
            for op in result.openings:
                x, y = op.insert
                self._scene.addEllipse(x - 0.15, -y - 0.15, 0.3, 0.3, opening_pen)
            rect = self._scene.itemsBoundingRect().adjusted(-1, -1, 1, 1)
            self.setSceneRect(rect)
            self.fitInView(rect, Qt.KeepAspectRatio)

    class MainWindow(QMainWindow):  # type: ignore[misc]
        def __init__(self, config: PipelineConfig) -> None:
            super().__init__()
            self.setWindowTitle("Metraj — DWG/DXF mimari + yapisal metraj otomasyonu")
            self.resize(1280, 820)
            self._config = config
            self._pipeline = Pipeline(config)
            self._struct_pipeline = StructuralPipeline(default_structural_config())
            self._cad_path: Optional[Path] = None
            self._output_dir: Path = Path.cwd() / "build"
            self._validator_path: Optional[Path] = None
            self._worker: Optional[PipelineWorker] = None
            self._layer_include_user: Dict[str, str] = {}
            self._layer_exclude_user: Set[str] = set()
            self._last_structural_result: Optional[StructuralPipelineResult] = None
            #: Kullanici-secilen yapisal profil YAML. None ise paket-icindeki
            #: kumluca.yaml default'u kullanilir.
            self._active_struct_profile_path: Optional[Path] = None
            self._build_ui()

        def _build_ui(self) -> None:
            central = QWidget(self)
            layout = QVBoxLayout(central)

            # Top bar
            top = QHBoxLayout()
            self.cad_label = QLabel("CAD dosyasi secilmedi")
            top.addWidget(self.cad_label)
            choose_cad = QPushButton("DWG/DXF Sec...")
            choose_cad.clicked.connect(self._pick_cad)
            top.addWidget(choose_cad)
            self.out_label = QLabel(f"Cikti klasoru: {self._output_dir}")
            top.addWidget(self.out_label)
            choose_out = QPushButton("Cikti Klasoru...")
            choose_out.clicked.connect(self._pick_output)
            top.addWidget(choose_out)

            top.addWidget(QLabel("Mod:"))
            self.mode_combo = QComboBox()
            self.mode_combo.addItem("Otomatik", "auto")
            self.mode_combo.addItem("Mimari (mahal/kapi/pencere)", "architectural")
            self.mode_combo.addItem("Yapisal (kalip/beton)", "structural")
            top.addWidget(self.mode_combo)

            self.validator_check = QCheckBox("Referans Excel ile kıyasla")
            self.validator_check.setToolTip(
                "Çizimden hesaplanan metraj ile seçtiğiniz Excel dosyasını "
                "satır bazında karşılaştırır; rakamlar Excel'den alınmaz."
            )
            top.addWidget(self.validator_check)
            self.validator_btn = QPushButton("Referans Excel...")
            self.validator_btn.setEnabled(False)
            self.validator_btn.setToolTip("Kumluca tarzı referans metraj (.xlsx)")
            self.validator_btn.clicked.connect(self._pick_validator)
            top.addWidget(self.validator_btn)
            self.validator_label = QLabel("(yok)")
            self.validator_label.setMinimumWidth(160)
            top.addWidget(self.validator_label)
            top.addWidget(QLabel("Sapma eşiği:"))
            self.tolerance_spin = QDoubleSpinBox()
            self.tolerance_spin.setRange(0.05, 25.0)
            self.tolerance_spin.setValue(1.0)
            self.tolerance_spin.setSuffix(" %")
            self.tolerance_spin.setDecimals(2)
            self.tolerance_spin.setEnabled(False)
            self.tolerance_spin.setToolTip(
                "Satır bazında göreli sapma bu yüzdeyi aşınca uyarı verilir."
            )
            top.addWidget(self.tolerance_spin)
            self.validator_check.toggled.connect(self.validator_btn.setEnabled)
            self.validator_check.toggled.connect(self.tolerance_spin.setEnabled)

            self.run_btn = QPushButton("Metraji Calistir")
            self.run_btn.clicked.connect(self._run_pipeline)
            top.addWidget(self.run_btn)
            layout.addLayout(top)

            # Yapisal profil paneli (yapisal mod aktifken kullanilir)
            profile_row = QHBoxLayout()
            profile_row.addWidget(QLabel("Yapisal Profil:"))
            self.profile_label = QLabel("(default: kumluca.yaml)")
            self.profile_label.setMinimumWidth(280)
            self.profile_label.setStyleSheet("color: #555;")
            profile_row.addWidget(self.profile_label, 1)

            self.profile_load_btn = QPushButton("YAML Yukle...")
            self.profile_load_btn.setToolTip(
                "Diskten bir yapisal profil YAML'i sec (compare/auto-fit/UI cikti)."
            )
            self.profile_load_btn.clicked.connect(self._pick_profile_yaml)
            profile_row.addWidget(self.profile_load_btn)

            self.profile_config_btn = QPushButton("Yeni Profil (UI)...")
            self.profile_config_btn.setToolTip(
                "Excel-bagimsiz config sihirbazi: UI uzerinden CalcParams ayarla "
                "(Saf geometri / Yari kesit / Ozel + minha/kat-bazli/katman override)."
            )
            self.profile_config_btn.clicked.connect(self._open_config_wizard)
            profile_row.addWidget(self.profile_config_btn)

            self.profile_calibrate_btn = QPushButton("Excel ile Kalibre Et...")
            self.profile_calibrate_btn.setToolTip(
                "Referans Excel'den otomatik CalcParams fit (Faz 4 sihirbazi)."
            )
            self.profile_calibrate_btn.clicked.connect(self._open_calibration_wizard)
            profile_row.addWidget(self.profile_calibrate_btn)

            self.profile_reset_btn = QPushButton("Default'a Don")
            self.profile_reset_btn.setToolTip(
                "Active profili kaldir, paket-icindeki kumluca.yaml'a don."
            )
            self.profile_reset_btn.clicked.connect(self._reset_profile)
            profile_row.addWidget(self.profile_reset_btn)

            layout.addLayout(profile_row)

            # Mod degisince profil panelini enable/disable yap
            self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
            self._on_mode_changed()  # initial state

            # Tabs - mimari
            self.tabs = QTabWidget()
            self.mahal_table = QTableWidget()
            self.openings_table = QTableWidget()
            self.icmal_table = QTableWidget()
            self.warnings_list = QListWidget()
            self.plan_view = PlanView()
            self.tabs.addTab(self.plan_view, "2D Plan")
            self.tabs.addTab(self.mahal_table, "Mahal Listesi")
            self.tabs.addTab(self.openings_table, "Acikliklar")
            self.tabs.addTab(self.icmal_table, "Icmal")
            # Yapisal sekmeler
            self.kalip_table = QTableWidget()
            self.beton_table = QTableWidget()
            self.struct_summary = QTextBrowser()
            self.tabs.addTab(self.struct_summary, "Yapisal Ozet")
            self.tabs.addTab(self.kalip_table, "Kalip (m2)")
            self.tabs.addTab(self.beton_table, "Beton (m3)")
            self.layer_override_panel = QWidget()
            lov = QVBoxLayout(self.layer_override_panel)
            self.layer_override_intro = QTextBrowser()
            self.layer_override_intro.setOpenExternalLinks(False)
            self.layer_override_intro.setMaximumHeight(120)
            self.layer_override_intro.setHtml(
                "<p><b>Yapısal katmanlar</b> — Otomatik tanınmayan katmanlara <b>Manuel tür</b> "
                "seçin (ör. kolon). Tanınan ama saymak istemediğiniz katmanları "
                "<b>Hesaptan çıkar</b> ile devre dışı bırakın. "
                "Değişiklikler bir sonraki <i>Metrajı çalıştır</i> ile uygulanır.</p>"
            )
            lov.addWidget(self.layer_override_intro)
            lorow = QHBoxLayout()
            self.layer_override_reset_btn = QPushButton("Manuel seçimleri sıfırla")
            self.layer_override_reset_btn.clicked.connect(self._reset_layer_overrides)
            lorow.addWidget(self.layer_override_reset_btn)
            lorow.addStretch()
            lov.addLayout(lorow)
            self.layer_override_table = QTableWidget()
            lov.addWidget(self.layer_override_table)
            self.tabs.addTab(self.layer_override_panel, "Yapisal katmanlar")
            self.validation_panel = QWidget()
            vdog = QVBoxLayout(self.validation_panel)
            self.validation_intro = QTextBrowser()
            self.validation_intro.setMaximumHeight(130)
            self.validation_intro.setOpenExternalLinks(False)
            vdog.addWidget(self.validation_intro)
            self.validation_table = QTableWidget()
            vdog.addWidget(self.validation_table)
            self.tabs.addTab(self.validation_panel, "Dogrulama")
            self.tabs.addTab(self.warnings_list, "Uyarilar")
            layout.addWidget(self.tabs)

            self.validation_intro.setHtml(
                "<p><i>Yapısal modda isteğe bağlı referans Excel seçerek "
                "hesap ile doğrulayıcıyı satır satır burada karşılaştırabilirsiniz.</i></p>"
            )

            self.setCentralWidget(central)
            self.setStatusBar(QStatusBar(self))

        def _pick_cad(self) -> None:
            path, _ = QFileDialog.getOpenFileName(
                self, "CAD dosyasi sec", str(Path.home()),
                "CAD (*.dwg *.dxf)"
            )
            if not path:
                return
            self._cad_path = Path(path)
            self.cad_label.setText(f"CAD: {self._cad_path.name}")

        def _pick_output(self) -> None:
            path = QFileDialog.getExistingDirectory(self, "Cikti klasoru", str(self._output_dir))
            if not path:
                return
            self._output_dir = Path(path)
            self.out_label.setText(f"Cikti klasoru: {self._output_dir}")

        def _pick_validator(self) -> None:
            path, _ = QFileDialog.getOpenFileName(
                self,
                "Referans metraj Excel",
                str(self._validator_path or Path.home()),
                "Excel (*.xlsx *.xls)",
            )
            if not path:
                return
            self._validator_path = Path(path)
            self.validator_label.setText(self._validator_path.name)

        def _on_mode_changed(self) -> None:
            """Yapisal profil paneli sadece structural/auto modda aktif."""
            mode = self.mode_combo.currentData() or "auto"
            structural_active = mode in ("structural", "auto")
            for btn in (
                self.profile_load_btn,
                self.profile_config_btn,
                self.profile_calibrate_btn,
                self.profile_reset_btn,
            ):
                btn.setEnabled(structural_active)

        def _pick_profile_yaml(self) -> None:
            """Diskten profil YAML'i sec; aktif profil yap."""
            path, _ = QFileDialog.getOpenFileName(
                self, "Yapisal Profil YAML Sec",
                str(Path.cwd()), "YAML (*.yaml *.yml)",
            )
            if not path:
                return
            self._set_active_profile(Path(path))

        def _set_active_profile(self, path: Path) -> None:
            """Aktif yapisal profil olarak set et + UI'da goster."""
            try:
                cfg = StructuralConfig.from_file(path)
            except Exception as exc:
                QMessageBox.critical(
                    self, "Profil yuklenemedi",
                    f"YAML okuma hatasi:\n{exc}",
                )
                return
            self._active_struct_profile_path = path
            self.profile_label.setText(
                f"{path.name} — {cfg.project_name}"
            )
            self.profile_label.setStyleSheet("color: #006400; font-weight: bold;")
            self.statusBar().showMessage(
                f"Yapisal profil yuklendi: {path.name}", 5000,
            )

        def _reset_profile(self) -> None:
            self._active_struct_profile_path = None
            self.profile_label.setText("(default: kumluca.yaml)")
            self.profile_label.setStyleSheet("color: #555;")
            self.statusBar().showMessage("Yapisal profil default'a alindi", 3000)

        def _open_config_wizard(self) -> None:
            """Excel-bagimsiz config sihirbazini ac."""
            try:
                from .structural_config_dialog import StructuralConfigDialog
            except ImportError as exc:  # pragma: no cover
                QMessageBox.critical(
                    self, "Import hatasi",
                    f"structural_config_dialog yuklenemedi: {exc}",
                )
                return
            default_out = self._suggest_profile_output_path()
            dlg = StructuralConfigDialog(
                parent=self,
                initial_preset="geometry_full",
                initial_output=default_out,
            )
            if dlg.exec() == QDialog.Accepted:
                # Dialog kendi YAML'ini yazdi; output_label'dan yolu al
                yaml_path = Path(dlg.output_label.text().strip())
                if yaml_path.is_file():
                    self._set_active_profile(yaml_path)

        def _open_calibration_wizard(self) -> None:
            """Excel ile kalibrasyon sihirbazini ac (Faz 4 auto-fit)."""
            try:
                from .calibration_wizard import CalibrationWizard
            except ImportError as exc:  # pragma: no cover
                QMessageBox.critical(
                    self, "Import hatasi",
                    f"calibration_wizard yuklenemedi: {exc}",
                )
                return
            # CAD ve Excel UI'da secilmis olabilir; on-fill et
            initial_cad = self._cad_path
            initial_ref = self._validator_path
            default_out = self._suggest_profile_output_path()
            dlg = CalibrationWizard(
                parent=self,
                initial_cad=initial_cad,
                initial_ref=initial_ref,
                initial_output=default_out,
            )
            if dlg.exec() == QDialog.Accepted:
                yaml_path = Path(dlg.out_edit.text().strip())
                if yaml_path.is_file():
                    self._set_active_profile(yaml_path)

        def _suggest_profile_output_path(self) -> Path:
            """Yeni profil icin makul bir varsayilan yol uretir."""
            if self._cad_path:
                return self._cad_path.with_suffix(".profile.yaml")
            return self._output_dir / "profile.yaml"

        def _struct_config_for_ui(self):
            """Yapisal pipeline icin UI'dan StructuralConfig uretir.

            Oncelik sirasi:
              1. Kullanici-secilen `_active_struct_profile_path` (varsa).
              2. Paket icindeki ``config/references/kumluca.yaml``.
              3. Jenerik default_structural_config().
            """
            base = None
            if self._active_struct_profile_path and self._active_struct_profile_path.is_file():
                try:
                    base = StructuralConfig.from_file(self._active_struct_profile_path)
                except Exception as exc:
                    logger.warning(
                        "Aktif profil yuklenemedi (%s), kumluca.yaml default'una donuluyor: %s",
                        self._active_struct_profile_path, exc,
                    )
                    base = None
            if base is None:
                kref = (
                    Path(__file__).resolve().parent.parent
                    / "config"
                    / "references"
                    / "kumluca.yaml"
                )
                if kref.is_file():
                    try:
                        base = StructuralConfig.from_file(kref)
                    except Exception as exc:
                        logger.warning(
                            "kumluca.yaml yuklenemedi (%s), jenerik yapisal sablon: %s",
                            kref, exc,
                        )
                        base = default_structural_config()
                else:
                    base = default_structural_config()
            if (
                self.validator_check.isChecked()
                and self._validator_path is not None
                and self._validator_path.is_file()
            ):
                rt = max(0.0001, float(self.tolerance_spin.value()) / 100.0)
                base = replace(
                    base,
                    reference_excel_path=str(self._validator_path.resolve()),
                    compare_to_reference=True,
                    validation_tolerance=rt,
                    excel_layout="kumluca",
                    snap_rows_to_reference=False,
                )
            return self._merge_structural_layer_overrides(base)

        def _merge_structural_layer_overrides(self, base: StructuralConfig) -> StructuralConfig:
            """YAML + arayüzdeki katman dahil / hariç listelerini birleştirir (UI baskın)."""
            ui_inc = dict(self._layer_include_user)
            ui_exc = set(self._layer_exclude_user)
            y_inc = dict(getattr(base, "structural_layer_include_kind", None) or {})
            y_exc = set(getattr(base, "structural_layer_exclude", None) or [])
            merged_inc = {**y_inc, **ui_inc}
            merged_exc = sorted(y_exc | ui_exc)
            return replace(
                base,
                structural_layer_include_kind=merged_inc,
                structural_layer_exclude=merged_exc,
            )

        def _run_pipeline(self) -> None:
            if not self._cad_path:
                QMessageBox.warning(self, "Eksik", "Lutfen bir DWG/DXF secin")
                return
            self.run_btn.setEnabled(False)
            mode = self.mode_combo.currentData() or "auto"
            self.statusBar().showMessage(f"Pipeline calisiyor... (mod={mode})")
            self._struct_pipeline = StructuralPipeline(self._struct_config_for_ui())
            worker = PipelineWorker(
                arch_pipeline=self._pipeline,
                struct_pipeline=self._struct_pipeline,
                cad_path=self._cad_path,
                output_dir=self._output_dir,
                oda_binary=None,
                mode=mode,
            )
            worker.finished_ok.connect(self._on_done)
            worker.finished_struct.connect(self._on_done_struct)
            worker.finished_err.connect(self._on_error)
            worker.finished.connect(lambda: self.run_btn.setEnabled(True))
            self._worker = worker
            worker.start()

        def _on_done(self, result: PipelineResult) -> None:
            self.statusBar().showMessage(
                f"Tamam (mimari): {len(result.rooms)} mahal, "
                f"{len(result.openings)} aciklik, "
                f"genel toplam {result.icmal.grand_total:,.2f} TL"
            )
            self._populate_mahal(result)
            self._populate_openings(result)
            self._populate_icmal(result)
            self._populate_warnings(result)
            self.plan_view.render_result(result)
            # Yapisal sekmeleri temizle
            self.kalip_table.setRowCount(0)
            self.beton_table.setRowCount(0)
            self.struct_summary.setHtml(
                "<p><i>Mimari mod calistirildi. Yapisal verilere gecmek icin "
                "yukaridan 'Yapisal' modunu secin.</i></p>"
            )
            self.validation_intro.setHtml(
                "<p><i>Mimari mod — yapısal doğrulama uygulanmadı.</i></p>"
            )
            self.validation_table.setRowCount(0)
            self.validation_table.setColumnCount(0)
            # Mimari sekmelerden birine gec
            self.tabs.setCurrentIndex(1)  # Mahal Listesi

        def _on_done_struct(self, result: StructuralPipelineResult) -> None:
            rep = result.report
            self.statusBar().showMessage(
                f"Tamam (yapisal): {result.plan_count} plan, "
                f"kalip={rep.formwork_total_m2:,.1f} m2, "
                f"beton={rep.concrete_total_m3:,.1f} m3"
            )
            self._populate_kalip(result)
            self._populate_beton(result)
            self._populate_struct_summary(result)
            self._populate_validation(result)
            self._populate_structural_layer_table(result)
            self._last_structural_result = result
            # Mimari sekmeleri temizle
            self.mahal_table.setRowCount(0)
            self.openings_table.setRowCount(0)
            self.icmal_table.setRowCount(0)
            self.warnings_list.clear()
            # Dogrulama veya ozet sekmesine gec
            if result.validation_detail is not None:
                self.tabs.setCurrentWidget(self.validation_panel)
            else:
                self.tabs.setCurrentWidget(self.struct_summary)

        def _on_error(self, kind: str, message: str) -> None:
            self.statusBar().showMessage(f"Hata: {message[:140]}")
            if kind == "oda_not_found":
                dlg = OdaInstallDialog(self)
                dlg.exec()
                return
            QMessageBox.critical(self, "Hata", message)

        def _populate_mahal(self, result: PipelineResult) -> None:
            cols = ["Kat", "Kod", "Ad", "Doseme", "Duvar", "Tavan", "Supurgelik",
                    "Alan (m2)", "Cevre (m)", "Yukseklik (m)",
                    "Net Doseme", "Net Duvar", "Net Tavan", "Net Supurgelik",
                    "Kapi", "Pencere"]
            self.mahal_table.setColumnCount(len(cols))
            self.mahal_table.setHorizontalHeaderLabels(cols)
            self.mahal_table.setRowCount(len(result.quantities))
            for row_idx, q in enumerate(result.quantities):
                values = [
                    q.room.floor, q.room.code, q.room.name,
                    q.room.floor_tip or "", q.room.wall_tip or "",
                    q.room.ceiling_tip or "", q.room.skirting_tip or "",
                    f"{q.room.area:.2f}", f"{q.room.perimeter:.2f}",
                    f"{q.room.height:.2f}",
                    f"{q.net_floor_m2:.2f}", f"{q.net_wall_m2:.2f}",
                    f"{q.net_ceiling_m2:.2f}", f"{q.net_skirting_m:.2f}",
                    str(q.door_count), str(q.window_count),
                ]
                for col, val in enumerate(values):
                    self.mahal_table.setItem(row_idx, col, QTableWidgetItem(str(val)))
            self.mahal_table.resizeColumnsToContents()

        def _populate_openings(self, result: PipelineResult) -> None:
            cols = ["Kat", "Tur", "Mahal", "En (m)", "Yukseklik (m)", "Olcu", "Blok"]
            self.openings_table.setColumnCount(len(cols))
            self.openings_table.setHorizontalHeaderLabels(cols)
            self.openings_table.setRowCount(len(result.openings))
            for row_idx, o in enumerate(result.openings):
                values = [
                    o.floor or "", o.kind, o.room_code or "",
                    f"{o.width_m:.2f}", f"{o.height_m:.2f}",
                    o.dim_label, o.block_name,
                ]
                for col, val in enumerate(values):
                    self.openings_table.setItem(row_idx, col, QTableWidgetItem(str(val)))
            self.openings_table.resizeColumnsToContents()

        def _populate_icmal(self, result: PipelineResult) -> None:
            cols = ["Kategori", "Poz", "Tanim", "Birim", "Miktar", "Birim Fiyat", "Tutar (TL)"]
            self.icmal_table.setColumnCount(len(cols))
            self.icmal_table.setHorizontalHeaderLabels(cols)
            self.icmal_table.setRowCount(len(result.icmal.rows))
            for row_idx, entry in enumerate(result.icmal.rows):
                values = [entry.kategori, entry.poz_no, entry.tanim, entry.birim,
                          f"{entry.miktar:.2f}", f"{entry.birim_fiyat:.2f}",
                          f"{entry.tutar:,.2f}"]
                for col, val in enumerate(values):
                    self.icmal_table.setItem(row_idx, col, QTableWidgetItem(str(val)))
            self.icmal_table.resizeColumnsToContents()

        def _populate_warnings(self, result: PipelineResult) -> None:
            """Mimari pipeline: autodetect / konfig bosluklarini Uyarilar sekmesine yazar."""
            self.warnings_list.clear()
            items: List[str] = []
            if result.autodetect_report and result.autodetect_report.unmatched:
                n = len(result.autodetect_report.unmatched)
                u = result.autodetect_report.unmatched
                head = ", ".join(u[:40])
                extra = f" ... (+{n - 40} daha)" if n > 40 else ""
                items.append(f"Otomatik eslestirilemeyen katman ({n}): {head}{extra}")
            if result.config_gaps is not None and result.config_gaps.has_gaps():
                items.extend(result.config_gaps.summary().splitlines())
            if not items:
                self.warnings_list.addItem("Uyari yok (katman/poz tipi tutuyor).")
            else:
                for line in items:
                    self.warnings_list.addItem(line)

        def _populate_kalip(self, result: StructuralPipelineResult) -> None:
            cols = ["Kat", "Kategori", "Aciklama", "Uzunluk/Cevre (m)", "Y/H (m)", "Toplam (m2)"]
            self.kalip_table.setColumnCount(len(cols))
            self.kalip_table.setHorizontalHeaderLabels(cols)
            rows = result.report.formwork_rows
            self.kalip_table.setRowCount(len(rows) + 1)
            for ri, r in enumerate(rows):
                vals = [
                    r.floor_label or "", r.category, r.label,
                    f"{r.qty1:.3f}", f"{r.qty2:.3f}", f"{r.total:.3f}",
                ]
                for ci, v in enumerate(vals):
                    item = QTableWidgetItem(v)
                    if r.total < 0:
                        item.setForeground(QBrush(QColor(192, 0, 0)))
                    self.kalip_table.setItem(ri, ci, item)
            # Toplam
            tot_item = QTableWidgetItem("TOPLAM")
            tot_item.setFont(self.font())
            self.kalip_table.setItem(len(rows), 2, tot_item)
            self.kalip_table.setItem(
                len(rows), 5,
                QTableWidgetItem(f"{result.report.formwork_total_m2:,.2f} m2"),
            )
            self.kalip_table.resizeColumnsToContents()

        def _populate_beton(self, result: StructuralPipelineResult) -> None:
            cols = ["Kat", "Kategori", "Aciklama", "Alan/Uzunluk", "Y/H (m)", "Toplam (m3)"]
            self.beton_table.setColumnCount(len(cols))
            self.beton_table.setHorizontalHeaderLabels(cols)
            rows = result.report.concrete_rows
            self.beton_table.setRowCount(len(rows) + 1)
            for ri, r in enumerate(rows):
                vals = [
                    r.floor_label or "", r.category, r.label,
                    f"{r.qty1:.3f}", f"{r.qty2:.3f}", f"{r.total:.3f}",
                ]
                for ci, v in enumerate(vals):
                    self.beton_table.setItem(ri, ci, QTableWidgetItem(v))
            self.beton_table.setItem(len(rows), 2, QTableWidgetItem("TOPLAM"))
            self.beton_table.setItem(
                len(rows), 5,
                QTableWidgetItem(f"{result.report.concrete_total_m3:,.2f} m3"),
            )
            self.beton_table.resizeColumnsToContents()

        def _populate_struct_summary(self, result: StructuralPipelineResult) -> None:
            rep = result.report
            counts: Dict[str, int] = {}
            for el in result.smodel.all_elements():
                counts[el.kind] = counts.get(el.kind, 0) + 1
            kinds_html = "<table border='1' cellpadding='4' style='border-collapse:collapse'>"
            kinds_html += "<tr><th>Eleman Turu</th><th>Adet</th></tr>"
            for k, v in sorted(counts.items()):
                kinds_html += f"<tr><td>{k}</td><td align='right'>{v}</td></tr>"
            kinds_html += "</table>"

            floors_html = "<table border='1' cellpadding='4' style='border-collapse:collapse'>"
            floors_html += "<tr><th>Kat</th><th>Etiket</th><th>H (m)</th><th>Eleman</th></tr>"
            for fp in result.smodel.floors:
                floors_html += (
                    f"<tr><td>Plan {fp.index}</td>"
                    f"<td>{fp.label}</td>"
                    f"<td align='right'>{fp.storey_height_m:.2f}</td>"
                    f"<td align='right'>{len(fp.elements)}</td></tr>"
                )
            floors_html += "</table>"

            html = f"""
            <h2>Yapisal Metraj Ozeti</h2>
            <p><b>Plan kumesi sayisi:</b> {result.plan_count}<br/>
               <b>Eleman sayisi (toplam):</b> {len(result.smodel.all_elements())}<br/>
               <b>Kalip toplami:</b> {rep.formwork_total_m2:,.2f} m<sup>2</sup><br/>
               <b>Beton toplami:</b> {rep.concrete_total_m3:,.2f} m<sup>3</sup></p>

            <h3>Eleman dagilimi</h3>
            {kinds_html}

            <h3>Kat dagilimi</h3>
            {floors_html}

            <h3>Notlar</h3>
            <ul>
            {''.join(f'<li>{n}</li>' for n in (rep.notes or ['(yok)']))}
            </ul>
            """
            if result.excel_path:
                html += f"<p><b>Excel cikti:</b> {result.excel_path}</p>"
            if result.validation_summary_path:
                html += (
                    f"<p><b>Dogrulama ozeti dosyasi:</b> "
                    f"{result.validation_summary_path}</p>"
                )
            self.struct_summary.setHtml(html)

        def _populate_validation(self, result: StructuralPipelineResult) -> None:
            vd = result.validation_detail
            if vd is None:
                parts = [
                    "<p><i>Referans Excel ile kıyaslama yapılmadı.</i></p>",
                    "<p>Üst bardan <b>Referans Excel ile kıyasla</b> seçip "
                    "dosyayı gösterin ve yapısal metrajı tekrar çalıştırın.</p>",
                ]
                if self.validator_check.isChecked() and (
                    not self._validator_path or not self._validator_path.is_file()
                ):
                    parts = [
                        "<p style='color:#a60'><b>Uyarı:</b> Kıyaslama işaretli "
                        "ama geçerli bir referans Excel seçilmedi.</p>",
                    ]
                self.validation_intro.setHtml("".join(parts))
                self.validation_table.setRowCount(0)
                self.validation_table.setColumnCount(0)
                return

            tol_pct = vd.tolerance * 100.0
            intro = (
                f"<h3>Doğrulama özeti</h3>"
                f"<p><b>Referans dosya:</b> {vd.reference_path.name}<br/>"
                f"<b>Eşik (göreli sapma):</b> ±{tol_pct:.2f}%<br/>"
                f"<b>Kalıp — max sapma:</b> {vd.max_rel_error_formwork * 100:.2f}%<br/>"
                f"<b>Beton — max sapma:</b> {vd.max_rel_error_concrete * 100:.2f}%<br/>"
                f"<b>Uyarı satırı (eşik / eksik etiket):</b> {len(vd.warning_lines)}</p>"
            )
            if result.validation_summary_path:
                intro += (
                    f"<p><small>Tam liste: "
                    f"<code>{result.validation_summary_path}</code></small></p>"
                )
            self.validation_intro.setHtml(intro)

            cols = ["Bölüm", "Etiket", "Hesap", "Referans", "|Sapma| %", "Durum"]
            self.validation_table.setColumnCount(len(cols))
            self.validation_table.setHorizontalHeaderLabels(cols)
            self.validation_table.setRowCount(len(vd.row_details))

            status_tr = {
                "ok": "Tamam",
                "esik_ustu": "Eşik üstü",
                "sadece_hesap": "Yalnız çizimde",
                "sadece_referans": "Yalnız referansta",
            }
            col_green = QColor(0, 110, 40)
            col_red = QColor(180, 0, 0)
            col_orange = QColor(180, 90, 0)

            for ri, row in enumerate(vd.row_details):
                h = f"{row.computed:.4f}" if row.computed is not None else "—"
                r = f"{row.reference:.4f}" if row.reference is not None else "—"
                if row.rel_error is not None:
                    sp = f"{row.rel_error * 100:.2f}"
                else:
                    sp = "—"
                st = status_tr.get(row.status, row.status)
                vals = [row.section, row.label, h, r, sp, st]
                for ci, val in enumerate(vals):
                    item = QTableWidgetItem(val)
                    if row.status == "ok":
                        item.setForeground(QBrush(col_green))
                    elif row.status == "esik_ustu":
                        item.setForeground(QBrush(col_red))
                    elif row.status.startswith("sadece"):
                        item.setForeground(QBrush(col_orange))
                    self.validation_table.setItem(ri, ci, item)
            self.validation_table.resizeColumnsToContents()

        def _reset_layer_overrides(self) -> None:
            self._layer_include_user.clear()
            self._layer_exclude_user.clear()
            if self._last_structural_result is not None:
                self._populate_structural_layer_table(self._last_structural_result)

        def _populate_structural_layer_table(self, result: StructuralPipelineResult) -> None:
            ad = result.layer_report_autodetect
            if not ad or not result.source_layers:
                self.layer_override_table.setRowCount(0)
                self.layer_override_table.setColumnCount(0)
                return
            kinds = sorted(get_args(ElementKind))
            cols = ["Katman", "Otomatik tur", "Manuel tur", "Hesaptan cikar"]
            self.layer_override_table.setColumnCount(len(cols))
            self.layer_override_table.setHorizontalHeaderLabels(cols)
            rows = result.source_layers
            self.layer_override_table.setRowCount(len(rows))
            for ri, layer in enumerate(rows):
                self.layer_override_table.setItem(ri, 0, QTableWidgetItem(layer))
                ak = ad.layer_to_kind.get(layer)
                if ak:
                    auto_txt = ak
                elif layer in ad.unmatched:
                    auto_txt = "(eslesmedi)"
                else:
                    auto_txt = ""
                self.layer_override_table.setItem(ri, 1, QTableWidgetItem(auto_txt))
                combo = QComboBox()
                combo.addItem("(otomatik)", "")
                for kk in kinds:
                    combo.addItem(kk, kk)
                if layer in self._layer_include_user:
                    idx = combo.findData(self._layer_include_user[layer])
                    if idx >= 0:
                        combo.setCurrentIndex(idx)
                combo.setEnabled(layer not in self._layer_exclude_user)
                combo.currentIndexChanged.connect(
                    lambda _i, lay=layer, box=combo: self._apply_layer_kind_from_combo(lay, box),
                )
                self.layer_override_table.setCellWidget(ri, 2, combo)
                xcb = QCheckBox()
                xcb.setChecked(layer in self._layer_exclude_user)
                xcb.toggled.connect(
                    lambda on, lay=layer: self._apply_layer_exclude_toggled(lay, on),
                )
                self.layer_override_table.setCellWidget(ri, 3, xcb)
            self.layer_override_table.resizeColumnsToContents()

        def _apply_layer_kind_from_combo(self, layer: str, box: QComboBox) -> None:
            data = box.currentData()
            if not data:
                self._layer_include_user.pop(layer, None)
            else:
                self._layer_include_user[str(layer)] = str(data)

        def _apply_layer_exclude_toggled(self, layer: str, checked: bool) -> None:
            layer = str(layer)
            if checked:
                self._layer_exclude_user.add(layer)
                self._layer_include_user.pop(layer, None)
            else:
                self._layer_exclude_user.discard(layer)
            for ri in range(self.layer_override_table.rowCount()):
                it = self.layer_override_table.item(ri, 0)
                if it is not None and it.text() == layer:
                    combo = self.layer_override_table.cellWidget(ri, 2)
                    if isinstance(combo, QComboBox):
                        combo.setEnabled(not checked)
                        if checked:
                            combo.blockSignals(True)
                            combo.setCurrentIndex(0)
                            combo.blockSignals(False)
                    break

else:  # pragma: no cover - PySide6 missing

    class MainWindow:  # type: ignore[no-redef]
        def __init__(self, *args, **kwargs) -> None:
            raise RuntimeError("PySide6 yuklu degil")
