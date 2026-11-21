"""Real-model UI self-test: one German turn through the window, then the shell (CAP-0168).

After the turn it navigates to every enabled workspace, stops the session with the session
strip's **Stop (F9)** from Settings and returns to Conversation; the transcript and the pair
must be unchanged (spec VoR-01, E2E C-03). The sidebar must list seven entries and open the
Meeting page with **Start meeting** (CAP-0177 E2E C-02); no meeting is started. The visit
includes the Language packs page (CAP-0171 C-03). Needs the provisioned models (D-01).
"""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

os.environ.setdefault("QT_OPENGL", "software")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

from lianiq.app import build_pipeline
from lianiq.audio.wav import read_pcm16_mono
from lianiq.config import AppConfig
from lianiq.domain import TranslationResult
from lianiq.languages.registry import LanguageId
from lianiq.logging_setup import configure_logging

# Loading the models (torch is imported then) has its own budget: on a cold 4-vCPU VM it
# took longer than the whole former 90 s (native run 44267851808, C-03). The turn keeps 90 s
# from the moment the models are ready.
WARM_UP_TIMEOUT_MS = 600_000
TURN_TIMEOUT_MS = 90_000


def main() -> int:
    from PySide6.QtCore import QCoreApplication, Qt, QTimer
    from PySide6.QtWidgets import QApplication

    from lianiq.ui.main_window import MainWindow
    from lianiq.ui.shell.session_owner import SessionState
    from lianiq.ui.shell.workspaces import WorkspaceId

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    config = AppConfig.load()
    configure_logging(Path("logs"), "INFO")
    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_UseSoftwareOpenGL)
    application = QApplication(sys.argv)
    pipeline = build_pipeline(config)
    window = MainWindow(config, pipeline, persist_settings=False)
    window.show()

    outcome = {"code": 1}
    stage = {"ready": False}

    def submit_probe() -> None:
        try:
            source_wav = pipeline.voice_synthesizer().synthesize(
                "Guten Tag, wie geht es Ihnen?", LanguageId("de")
            )
            try:
                utterance = read_pcm16_mono(source_wav)
            finally:
                source_wav.unlink(missing_ok=True)
            window.runner.submit(utterance)
        except Exception as exc:  # noqa: BLE001 - diagnostic boundary reports all failures.
            window.bridge.error.emit(f"UI self-test setup failed: {exc}")

    def on_session_ready(_generation: int, ready: bool, message: str) -> None:
        if not ready:
            print(f"FAIL model warm-up: {message}", flush=True)
            application.exit(2)
            return
        print("Models for the selected mode ready; UI pipeline is listening", flush=True)
        stage["ready"] = True
        QTimer.singleShot(TURN_TIMEOUT_MS, on_timeout)
        threading.Thread(target=submit_probe, name="ui-self-test-input", daemon=True).start()

    def check_navigation() -> None:
        """Visit every enabled workspace, Stop from Settings, return to Conversation."""
        transcript = window.source_text.toPlainText()
        pair = window.pair_combo.currentText()
        if len(window.navigation.buttons) != 7:
            print(f"FAIL navigation: {len(window.navigation.buttons)} sidebar entries", flush=True)
            application.exit(8)
            return
        visits = (
            WorkspaceId.MEETING,
            WorkspaceId.TEXT_TRANSLATION,
            WorkspaceId.CALL_BRIDGE,
            WorkspaceId.LANGUAGE_PACKS,  # CAP-0171: showing the page starts no job
            WorkspaceId.SETTINGS,
        )
        for workspace in visits:
            window.navigation.buttons[workspace].click()
            application.processEvents()
            if window.current_workspace() is not workspace or not window.stop_button.isVisible():
                print(f"FAIL navigation: {workspace.value} without the session strip", flush=True)
                application.exit(5)
                return
            if workspace is WorkspaceId.MEETING and not window.meeting.start_button.isVisible():
                print("FAIL navigation: Meeting without Start meeting", flush=True)
                application.exit(9)
                return
        window.stop_button.click()  # Stop (F9) in the session strip, from Settings
        application.processEvents()
        if window.capture.running or window.session_owner.state is not SessionState.IDLE:
            print("FAIL navigation: Stop from Settings did not stop the session", flush=True)
            application.exit(6)
            return
        window.navigation.buttons[WorkspaceId.CONVERSATION].click()
        application.processEvents()
        if (
            window.source_text.toPlainText() != transcript
            or window.pair_combo.currentText() != pair
        ):
            print("FAIL navigation: transcript or pair changed", flush=True)
            application.exit(7)
            return
        print(
            "PASS navigation: seven sidebar entries, Meeting opened, Stop from Settings; "
            "transcript and pair unchanged",
            flush=True,
        )
        outcome["code"] = 0
        QTimer.singleShot(500, application.quit)

    def on_result(result: TranslationResult) -> None:
        print(
            f"PASS UI pipeline: {result.total_seconds:.3f} s, translated={result.translated_text}",
            flush=True,
        )
        QTimer.singleShot(0, check_navigation)

    def on_error(message: str) -> None:
        print(f"FAIL UI pipeline: {message}", flush=True)
        application.exit(3)

    def on_timeout() -> None:
        print("FAIL UI pipeline: timed out", flush=True)
        application.exit(4)

    def on_warm_up_timeout() -> None:
        if not stage["ready"]:
            print("FAIL model warm-up: timed out", flush=True)
            application.exit(10)

    window.bridge.session_ready.connect(on_session_ready)
    window.bridge.result.connect(on_result)
    window.bridge.error.connect(on_error)
    QTimer.singleShot(WARM_UP_TIMEOUT_MS, on_warm_up_timeout)
    # Models load on Start, for the selected mode only.
    window.mode_combo.setCurrentIndex(window.mode_combo.findData(LanguageId("de")))
    QTimer.singleShot(0, window.start_listening)
    application.exec()
    window.close()
    return outcome["code"]


if __name__ == "__main__":
    raise SystemExit(main())
