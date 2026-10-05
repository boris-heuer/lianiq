from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

os.environ.setdefault("QT_OPENGL", "software")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

from offline_translator.app import build_pipeline
from offline_translator.audio.wav import read_pcm16_mono
from offline_translator.config import AppConfig
from offline_translator.domain import Language, TranslationResult
from offline_translator.logging_setup import configure_logging

TIMEOUT_MS = 90_000


def main() -> int:
    from PySide6.QtCore import QCoreApplication, Qt, QTimer
    from PySide6.QtWidgets import QApplication

    from offline_translator.ui.main_window import MainWindow

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    config = AppConfig.load()
    configure_logging(Path("logs"), "INFO")
    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_UseSoftwareOpenGL)
    application = QApplication(sys.argv)
    pipeline, synthesizer = build_pipeline(config)
    window = MainWindow(config, pipeline, persist_settings=False)
    window.set_synthesizer_reference(synthesizer)
    window.show()

    outcome = {"code": 1}

    def submit_probe() -> None:
        try:
            source_wav = synthesizer.synthesize(
                "Guten Tag, wie geht es Ihnen?", Language.GERMAN
            )
            try:
                utterance = read_pcm16_mono(source_wav)
            finally:
                source_wav.unlink(missing_ok=True)
            window.runner.submit(utterance)
        except Exception as exc:  # noqa: BLE001 - diagnostic boundary reports all failures.
            window.bridge.error.emit(f"UI self-test setup failed: {exc}")

    def on_models_ready(ready: bool, message: str) -> None:
        if not ready:
            print(f"FAIL model warm-up: {message}", flush=True)
            application.exit(2)
            return
        print("Models ready; starting microphone and UI pipeline", flush=True)
        window.mode_combo.setCurrentText("German → Mandarin")
        window.start_listening()
        threading.Thread(target=submit_probe, name="ui-self-test-input", daemon=True).start()

    def on_result(result: TranslationResult) -> None:
        print(
            f"PASS UI pipeline: {result.total_seconds:.3f} s, "
            f"translated={result.translated_text}",
            flush=True,
        )
        outcome["code"] = 0
        QTimer.singleShot(500, application.quit)

    def on_error(message: str) -> None:
        print(f"FAIL UI pipeline: {message}", flush=True)
        application.exit(3)

    def on_timeout() -> None:
        print("FAIL UI pipeline: timed out", flush=True)
        application.exit(4)

    window.bridge.models_ready.connect(on_models_ready)
    window.bridge.result.connect(on_result)
    window.bridge.error.connect(on_error)
    QTimer.singleShot(TIMEOUT_MS, on_timeout)
    application.exec()
    window.close()
    return outcome["code"]


if __name__ == "__main__":
    raise SystemExit(main())
