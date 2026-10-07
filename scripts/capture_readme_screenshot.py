from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_OPENGL", "software")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
os.environ.setdefault("QT_SCALE_FACTOR", "1")

from lianiq.audio.endpoints import EndpointInventory
from lianiq.config import AppConfig
from lianiq.pipeline import TranslationPipeline


class _ReadyRecognizer:
    device = "cpu"

    @staticmethod
    def warm_up() -> None:
        return None


class _ReadyTranslator:
    @staticmethod
    def warm_up() -> None:
        return None


def main() -> int:
    from PySide6.QtCore import QCoreApplication, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    import lianiq.ui.main_window as main_window_module

    root = Path(__file__).resolve().parent.parent
    output = root / "docs" / "assets" / "application-ui.png"

    # The public screenshot must never enumerate or persist host-specific devices.
    main_window_module.list_audio_devices = list
    main_window_module.list_audio_endpoints = lambda: EndpointInventory([])

    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_UseSoftwareOpenGL)
    application = QApplication(sys.argv)
    application.setApplicationName("lianiq screenshot capture")
    pipeline = TranslationPipeline(
        _ReadyRecognizer(),
        _ReadyTranslator(),
        synthesizer=None,
        playback=None,
    )
    window = main_window_module.MainWindow(AppConfig(), pipeline, persist_settings=False)
    window.show()
    QTest.qWait(500)
    application.processEvents()

    screenshot = window.grab()
    saved = screenshot.save(str(output), "PNG")
    window.close()
    application.processEvents()
    if not saved:
        print(f"Could not save screenshot to {output}", file=sys.stderr)
        return 1
    print(f"Saved sanitized {screenshot.width()}x{screenshot.height()} screenshot to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
