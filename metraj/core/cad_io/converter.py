"""DWG <-> DXF converter using ODA File Converter.

ODA File Converter is the de facto open-source-friendly tool for DWG translation.
It is shipped as a separate binary that the user must install once.  This module
wraps the CLI in a robust, cross-platform interface and degrades gracefully when
the binary is not installed (DXF can still be processed directly).
"""
from __future__ import annotations

import logging
import os
import platform
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional

logger = logging.getLogger(__name__)


_DOWNLOAD_URL = "https://www.opendesign.com/guestfiles/oda_file_converter"


def _platform_install_help() -> str:
    """Platforma ozgu kurulum talimati uretir."""
    system = platform.system()
    if system == "Darwin":
        return (
            f"macOS icin kurulum:\n"
            f"  1) Tarayicidan: {_DOWNLOAD_URL}\n"
            f"     'macOS' bolumunden uygun '.dmg' dosyasini indir.\n"
            f"  2) DMG'yi acip ODAFileConverter.app'i Applications klasorune\n"
            f"     surukle. (.app sag tik > 'Open' ile ilk acista Apple'in\n"
            f"     'unidentified developer' uyarisini gec.)\n"
            f"  3) Uygulamayi tekrar baslat -- otomatik bulunacaktir.\n"
            f"\n"
            f"Alternatif (kurulum yok):\n"
            f"  AutoCAD/BricsCAD'da DWG'i acip 'File > Save As > AutoCAD DXF'\n"
            f"  ile DXF olarak kaydedin ve onu yukleyin.\n"
        )
    if system == "Windows":
        return (
            f"Windows icin kurulum:\n"
            f"  1) Tarayicidan: {_DOWNLOAD_URL}\n"
            f"     'Windows 64' bolumunden '.exe' kurucusu indir.\n"
            f"  2) Kurulumu tamamla (varsayilan yol uygundur).\n"
            f"  3) Uygulamayi tekrar baslat.\n"
        )
    if system == "Linux":
        return (
            f"Linux icin kurulum:\n"
            f"  1) Tarayicidan: {_DOWNLOAD_URL}\n"
            f"     Distronuza uygun '.deb' veya '.rpm' indir, ya da\n"
            f"     conda forge: 'conda install -c conda-forge libredwg'\n"
            f"  2) Kurulumdan sonra uygulamayi tekrar baslat.\n"
        )
    return f"Lutfen ODA File Converter'i kurun: {_DOWNLOAD_URL}"


class OdaNotFoundError(RuntimeError):
    """Raised when ODA File Converter binary cannot be located."""

    def __init__(self, *, custom_path: Optional[str | os.PathLike[str]] = None) -> None:
        msg = (
            "DWG dosyalarini okumak icin 'ODA File Converter' (ucretsiz) "
            "gerekiyor.\n\n"
            f"{_platform_install_help()}\n"
            "Ya da elinizdeki dosyayi DXF olarak kaydetmek bu araca olan "
            "ihtiyaci tamamen ortadan kaldirir."
        )
        if custom_path:
            msg += f"\n\nVerilen yol bulunamadi: {custom_path}"
        super().__init__(msg)


# ODA versions ship under various paths; we probe the common ones.
_DEFAULT_BINARY_NAMES = (
    "ODAFileConverter",
    "ODAFileConverter.exe",
    "TeighaFileConverter",
)
_DEFAULT_SEARCH_DIRS = (
    "/Applications/ODAFileConverter.app/Contents/MacOS",
    "/usr/bin",
    "/usr/local/bin",
    "/opt/oda/ODAFileConverter",
    r"C:\Program Files\ODA\ODAFileConverter",
)


@dataclass(frozen=True)
class ConversionOptions:
    """Knobs for an ODA conversion run."""

    output_version: str = "ACAD2018"
    output_format: str = "DXF"
    recurse: bool = False
    audit: bool = True


class DwgConverter:
    """Convert DWG files to DXF using the ODA File Converter CLI.

    Parameters
    ----------
    binary_path:
        Optional explicit path to the ODA executable.  When omitted the
        common install locations are probed and ``$PATH`` is checked.
    """

    def __init__(self, binary_path: Optional[str | os.PathLike[str]] = None) -> None:
        self._binary_path = self._resolve_binary(binary_path)

    @property
    def binary_path(self) -> Optional[Path]:
        return self._binary_path

    @property
    def is_available(self) -> bool:
        return self._binary_path is not None

    @staticmethod
    def _resolve_binary(explicit: Optional[str | os.PathLike[str]]) -> Optional[Path]:
        if explicit:
            p = Path(explicit)
            return p if p.exists() else None
        for name in _DEFAULT_BINARY_NAMES:
            found = shutil.which(name)
            if found:
                return Path(found)
        for directory in _DEFAULT_SEARCH_DIRS:
            for name in _DEFAULT_BINARY_NAMES:
                candidate = Path(directory) / name
                if candidate.exists():
                    return candidate
        return None

    def convert_dwg_to_dxf(
        self,
        dwg_path: str | os.PathLike[str],
        output_dir: Optional[str | os.PathLike[str]] = None,
        options: ConversionOptions = ConversionOptions(),
    ) -> Path:
        """Translate a single DWG file into DXF and return the resulting path.

        ODA File Converter only operates on directories so we shuttle the file
        through a temporary input directory with an ASCII-safe name.  This
        avoids macOS quirks where the bundled CLI silently skips files whose
        names contain non-ASCII characters or that differ in extension case
        from the wildcard filter.
        """
        if not self.is_available:
            raise OdaNotFoundError()
        dwg = Path(dwg_path).resolve()
        if not dwg.exists():
            raise FileNotFoundError(dwg)
        out_dir = Path(output_dir).resolve() if output_dir else dwg.parent
        out_dir.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory(prefix="metraj_dwg_") as tmp:
            staging = Path(tmp) / "in"
            staging_out = Path(tmp) / "out"
            staging.mkdir()
            staging_out.mkdir()
            # ASCII-safe staging name — ODA on macOS uses Qt's case-sensitive
            # glob and chokes on some non-ASCII paths, so we always copy the
            # source as ``input.dwg`` and rename the output afterwards.
            staged_dwg = staging / "input.dwg"
            shutil.copy2(dwg, staged_dwg)

            cmd = [
                str(self._binary_path),
                str(staging),
                str(staging_out),
                options.output_version,
                options.output_format,
                "1" if options.recurse else "0",
                "1" if options.audit else "0",
                "*.dwg",
            ]
            logger.info("Running ODA File Converter: %s", " ".join(cmd))
            proc = subprocess.run(cmd, capture_output=True, text=True)
            produced = list(staging_out.glob("*.dxf"))
            if proc.returncode != 0 and not produced:
                raise RuntimeError(
                    f"ODA File Converter failed (rc={proc.returncode}): "
                    f"{proc.stderr.strip() or proc.stdout.strip()!r}"
                )
            if not produced:
                raise FileNotFoundError(
                    "ODA File Converter completed but produced no DXF file. "
                    f"stdout={proc.stdout.strip()!r} stderr={proc.stderr.strip()!r}\n"
                    "Olasi nedenler: kaynak dosya bozuk, sifrelenmis veya "
                    "desteklenmeyen bir AutoCAD surumunde."
                )
            staged_dxf = produced[0]
            out_dxf = out_dir / (dwg.stem + ".dxf")
            shutil.move(str(staged_dxf), str(out_dxf))
        return out_dxf

    def ensure_dxf(self, cad_path: str | os.PathLike[str]) -> Path:
        """Return a DXF path for any input file (DWG -> DXF, DXF passthrough)."""
        p = Path(cad_path).resolve()
        if p.suffix.lower() == ".dxf":
            return p
        if p.suffix.lower() != ".dwg":
            raise ValueError(f"Unsupported CAD file extension: {p.suffix}")
        return self.convert_dwg_to_dxf(p)


def find_oda_binary() -> Optional[Path]:
    """Convenience helper used by the UI/CLI to display install state."""
    return DwgConverter._resolve_binary(None)


def diagnose_dwg_support() -> dict:
    """Sistemde DWG dönüştürücü destegi var mı raporlar (UI/CLI için)."""
    binary = find_oda_binary()
    return {
        "platform": platform.system(),
        "platform_release": platform.release(),
        "oda_available": binary is not None,
        "oda_path": str(binary) if binary else None,
        "searched_paths": list(_DEFAULT_SEARCH_DIRS),
        "install_help": _platform_install_help(),
        "download_url": _DOWNLOAD_URL,
    }
