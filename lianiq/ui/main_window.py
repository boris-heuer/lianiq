"""The main window: composes the Conversation and Call Bridge workspaces (CAP-0168 WI-01).

The workspaces own their controls and logic (``ui/workspaces/``). The window keeps what they
share: the signal hand-off from worker threads (``UiBridge``), the status bar, the session
lock, the model warm-up generation and saving on close. Accessor properties keep the
established ``MainWindow`` attribute paths for scripts and tests.
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal, Slot
from PySide6.QtGui import QCloseEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMainWindow, QStatusBar, QVBoxLayout, QWidget

from lianiq.config import AppConfig
from lianiq.languages.modes import SessionPair
from lianiq.languages.requirements import ModeAvailability, describe
from lianiq.pipeline import TranslationPipeline
from lianiq.ui import strings
from lianiq.ui.workspaces.call_bridge import CallBridgeWorkspace
from lianiq.ui.workspaces.conversation import ConversationWorkspace


class UiBridge(QObject):
    result = Signal(object)
    held = Signal(object)
    held_resolved = Signal()
    error = Signal(str)
    busy = Signal(bool)
    level = Signal(float)
    session_ready = Signal(int, bool, str)  # start generation, ready, error message
    call_bridge_ready = Signal(int, bool, str)
    call_bridge_event = Signal(object)
    call_bridge_level = Signal(object, float)
    call_bridge_capture_fault = Signal(object, str)


def _forward(workspace: str, name: str) -> property:
    """A ``MainWindow`` attribute that reads and writes ``workspace.name``."""
    return property(
        lambda self: getattr(getattr(self, workspace), name),
        lambda self, value: setattr(getattr(self, workspace), name, value),
    )


class MainWindow(QMainWindow):
    # Conversation workspace.
    history = _forward("conversation", "history")
    devices = _forward("conversation", "devices")
    capture = _forward("conversation", "capture")
    runner = _forward("conversation", "runner")
    session_controller = _forward("conversation", "session_controller")
    pair_combo = _forward("conversation", "pair_combo")
    mode_combo = _forward("conversation", "mode_combo")
    input_combo = _forward("conversation", "input_combo")
    output_combo = _forward("conversation", "output_combo")
    model_combo = _forward("conversation", "model_combo")
    tts_checkbox = _forward("conversation", "tts_checkbox")
    gpu_checkbox = _forward("conversation", "gpu_checkbox")
    start_button = _forward("conversation", "start_button")
    stop_button = _forward("conversation", "stop_button")
    swap_button = _forward("conversation", "swap_button")
    held_turn_bar = _forward("conversation", "held_turn_bar")
    source_text = _forward("conversation", "source_text")
    target_text = _forward("conversation", "target_text")
    level_bar = _forward("conversation", "level_bar")
    state_label = _forward("conversation", "state_label")
    latency_label = _forward("conversation", "latency_label")
    # Call Bridge workspace.
    call_bridge_panel = _forward("call_bridge", "panel")
    call_bridge_controller = _forward("call_bridge", "controller")

    def __init__(
        self,
        config: AppConfig,
        pipeline: TranslationPipeline,
        persist_settings: bool = True,
    ) -> None:
        super().__init__()
        self.config = config
        self.pipeline = pipeline
        self.persist_settings = persist_settings
        self.bridge = UiBridge()
        self.bridge.error.connect(self.show_error)
        # Each Start gets a generation; a ready signal of a cancelled Start is ignored.
        self.start_generation = 0
        self.conversation = ConversationWorkspace(self)
        self.call_bridge = CallBridgeWorkspace(self)

        self.setWindowTitle("lianiq")
        self.resize(1120, 720)
        self.setMinimumSize(850, 560)
        self._build_ui()
        self._load_devices()
        self._apply_style()

        self.conversation.start_session_services()
        self.call_bridge_panel.set_models_ready(True)
        self.conversation.connect_selection()
        if "--diagnostic-wav" in sys.argv:
            argument_index = sys.argv.index("--diagnostic-wav") + 1
            if argument_index >= len(sys.argv):
                QTimer.singleShot(
                    0, lambda: self.show_error("--diagnostic-wav requires a WAV file path")
                )
            else:
                self.conversation.diagnostic_wav = Path(sys.argv[argument_index])
                QTimer.singleShot(0, self.start_listening)
        elif "--diagnostic-auto-start" in sys.argv:
            QTimer.singleShot(0, self.start_listening)

        QShortcut(QKeySequence("F8"), self, activated=self.start_listening)
        QShortcut(QKeySequence("F9"), self, activated=self.stop_listening)

    def _build_ui(self) -> None:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(16)

        title_row = QHBoxLayout()
        title = QLabel("lianiq")
        title.setObjectName("title")
        subtitle = QLabel("Local · Private · Optimized for Ryzen AI 7 350")
        subtitle.setObjectName("subtitle")
        title_row.addWidget(title)
        title_row.addStretch()
        title_row.addWidget(subtitle)
        layout.addLayout(title_row)

        self.conversation.build(layout, self.call_bridge.build_panel())

        self.setCentralWidget(root)
        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("Models load when the first speech segment is processed.")

    def _load_devices(self) -> None:
        # A failed device enumeration is reported once; the endpoints are then not listed.
        if self.conversation.load_devices():
            self.call_bridge.load_endpoints()

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, QWidget { background: #111827; color: #e5e7eb; font-size: 14px; }
            QLabel#title { font-size: 28px; font-weight: 700; color: #f9fafb; }
            QLabel#subtitle { color: #94a3b8; }
            QLabel#panelTitle { font-size: 17px; font-weight: 600; color: #cbd5e1; }
            QPlainTextEdit { background: #0b1220; border: 1px solid #334155; border-radius: 10px;
                             padding: 14px; font-size: 20px; selection-background-color: #2563eb; }
            QComboBox, QPushButton { background: #1e293b; border: 1px solid #475569;
                                    border-radius: 7px; padding: 8px 12px; }
            QComboBox:hover, QPushButton:hover { border-color: #60a5fa; }
            QPushButton#primaryButton { background: #2563eb; border-color: #3b82f6; font-weight: 600; }
            QPushButton:disabled { color: #64748b; background: #172033; }
            QProgressBar { background: #0b1220; border: 1px solid #334155; border-radius: 5px; }
            QProgressBar::chunk { background: #22c55e; border-radius: 4px; }
            QStatusBar { color: #94a3b8; }
            """
        )

    # Shared by both workspaces.

    def session_locked(self) -> bool:
        conversation = self.conversation
        return conversation.starting or conversation.capture.running or self.call_bridge.active()

    def prepare_in_background(self, session: SessionPair, ready: Signal) -> None:
        self.start_generation += 1
        generation = self.start_generation

        def prepare() -> None:
            try:
                self.pipeline.prepare(session)
            except Exception as exc:  # noqa: BLE001 - background boundary reports model failures.
                ready.emit(generation, False, str(exc))
            else:
                ready.emit(generation, True, "")

        threading.Thread(target=prepare, name="model-warmup", daemon=True).start()

    def describe_missing(self, availability: ModeAvailability) -> str:
        items = ", ".join(describe(item, self.pipeline.registry) for item in availability.missing)
        return strings.MODE_UNAVAILABLE.format(items=items)

    def show_unavailable(self, missing) -> None:
        self.show_error(self.describe_missing(ModeAvailability(False, tuple(missing))))

    @Slot(str)
    def show_error(self, message: str) -> None:
        self.statusBar().showMessage(message, 15_000)
        self.state_label.setText("Error")

    # Established entry points, used by the shortcuts, scripts and tests.

    @Slot()
    def start_listening(self) -> None:
        self.conversation.start_listening()

    @Slot()
    def stop_listening(self) -> None:
        self.conversation.stop_listening()

    @Slot()
    def start_call_bridge(self) -> None:
        self.call_bridge.start_call_bridge()

    @Slot()
    def stop_call_bridge(self) -> None:
        self.call_bridge.stop_call_bridge()

    def current_pair(self):
        return self.conversation.current_pair()

    def current_fixed_source(self):
        return self.conversation.current_fixed_source()

    def session_pair(self) -> SessionPair:
        return self.conversation.session_pair()

    def call_bridge_session(self) -> SessionPair:
        return self.call_bridge.session()

    def device_readiness(self):
        return self.conversation.device_readiness()

    def write_transcript(self, path: Path) -> None:
        self.conversation.write_transcript(path)

    def _refresh_availability(self) -> None:
        self.conversation.refresh_availability()

    _conversation_session = staticmethod(ConversationWorkspace.conversation_session)

    def closeEvent(self, event: QCloseEvent) -> None:
        self.stop_call_bridge()
        self.stop_listening()
        if self.persist_settings:
            self.call_bridge_panel.apply_to_config()
            self.conversation.save_routing()
            # ``config.voice_output`` holds the user's preference, kept even while a
            # missing voice disables the checkbox.
            self.config.save()
        event.accept()
