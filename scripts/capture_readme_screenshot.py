from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_OPENGL", "software")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
os.environ.setdefault("QT_SCALE_FACTOR", "1")

from lianiq.audio.devices import AudioDevice
from lianiq.audio.endpoints import EndpointInventory
from lianiq.config import AppConfig
from lianiq.languages import (
    BUILTIN_REGISTRY,
    CapabilityCatalog,
    ReadinessProbe,
    ReadinessStatus,
)
from lianiq.pipeline import TranslationPipeline

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = ROOT / "docs" / "assets" / "application-ui.png"
# Generic, host-independent devices; the public screenshot never enumerates real hardware.
GENERIC_DEVICES = (AudioDevice(0, "Microphone", 1, 0), AudioDevice(1, "Speakers", 0, 2))


class _ReadyRecognizer:
    device = "cpu"

    @staticmethod
    def warm_up(_languages=()) -> None:
        return None


class _ReadyTranslator:
    @staticmethod
    def warm_up(_edges=()) -> None:
        return None


class _ReadyProbe(ReadinessProbe):
    """Reports every configured model as installed, so no model files are needed."""

    def probe_file(self, path: Path) -> ReadinessStatus:
        return ReadinessStatus.INSTALLED

    def probe_directory(self, path: Path) -> ReadinessStatus:
        return ReadinessStatus.INSTALLED


def build_screenshot_pipeline(config: AppConfig) -> TranslationPipeline:
    """A pipeline over the default settings whose models report ready but never load."""
    catalog = CapabilityCatalog.from_config(config, BUILTIN_REGISTRY, _ReadyProbe(ROOT))
    return TranslationPipeline(
        _ReadyRecognizer(),
        _ReadyTranslator(),
        synthesizer=None,
        playback=None,
        registry=BUILTIN_REGISTRY,
        catalog=catalog,
    )


def main(argv: list[str] | None = None) -> int:
    from PySide6.QtCore import QCoreApplication, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    import lianiq.ui.main_window as main_window_module

    parser = argparse.ArgumentParser(description="Capture the sanitized README screenshot.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    output = parser.parse_args(argv).output

    patched = {
        "list_audio_devices": lambda: list(GENERIC_DEVICES),
        "list_audio_endpoints": lambda: EndpointInventory([]),
    }
    original = {name: getattr(main_window_module, name) for name in patched}
    for name, replacement in patched.items():
        setattr(main_window_module, name, replacement)
    try:
        application = QApplication.instance()
        if application is None:
            QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_UseSoftwareOpenGL)
            application = QApplication(sys.argv[:1])
            application.setApplicationName("lianiq screenshot capture")
        config = AppConfig()
        window = main_window_module.MainWindow(
            config, build_screenshot_pipeline(config), persist_settings=False
        )
        window.show()
        QTest.qWait(500)
        application.processEvents()

        screenshot = window.grab()
        saved = screenshot.save(str(output), "PNG")
        window.close()
        application.processEvents()
    finally:
        for name, value in original.items():
            setattr(main_window_module, name, value)
    if not saved:
        print(f"Could not save screenshot to {output}", file=sys.stderr)
        return 1
    print(f"Saved sanitized {screenshot.width()}x{screenshot.height()} screenshot to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
