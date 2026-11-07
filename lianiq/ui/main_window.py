"""The main window: the desktop shell over the workspaces (CAP-0168 WI-01, WI-02).

The workspaces own their controls and logic (``ui/workspaces/``). The window keeps what they
share: the signal hand-off from worker threads (``UiBridge``), the status bar, the session
lock, the model warm-up generation and saving on close. Accessor properties keep the
established ``MainWindow`` attribute paths for scripts and tests.

WI-02 shell (spec §2.3.1-§2.3.2): the navigation sidebar on the left, the workspace pages in
a ``QStackedWidget`` and the session strip with **Stop (F9)** below them. The one
``ActiveSessionOwner`` allows one session across modes; F9 stops the active session from
every workspace; Ctrl+1…Ctrl+6 select the enabled sidebar entries. Showing a page never
starts or stops capture or playback.
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal, Slot
from PySide6.QtGui import QCloseEvent, QKeySequence, QResizeEvent, QShortcut
from PySide6.QtWidgets import (
    QHBoxLayout,
    QMainWindow,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from lianiq.config import AppConfig
from lianiq.languages.modes import SessionPair
from lianiq.languages.requirements import ModeAvailability, describe
from lianiq.pipeline import TranslationPipeline
from lianiq.ui import strings
from lianiq.ui.shell.navigation import NavigationSidebar
from lianiq.ui.shell.session_owner import ActiveSessionOwner, SessionState
from lianiq.ui.shell.session_strip import SessionStrip
from lianiq.ui.shell.workspaces import DEFAULT_ENTRIES, WorkspaceId
from lianiq.ui.workspaces.call_bridge import CallBridgeWorkspace
from lianiq.ui.workspaces.conversation import ConversationWorkspace
from lianiq.ui.workspaces.settings import SettingsWorkspace

DEFAULT_SIZE = (1280, 720)
MINIMUM_SIZE = (850, 560)


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
    tts_checkbox = _forward("conversation", "tts_checkbox")
    start_button = _forward("conversation", "start_button")
    source_panel = _forward("conversation", "source_panel")
    target_panel = _forward("conversation", "target_panel")
    # Session strip: **Stop (F9)** stops the active session from every workspace.
    stop_button = _forward("session_strip", "stop_button")
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
    # Settings workspace: model profile and compute device moved here (AC-12).
    model_profile_field = _forward("settings", "model_profile_field")
    compute_device_field = _forward("settings", "compute_device_field")

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
        self.session_owner = ActiveSessionOwner()
        self.conversation = ConversationWorkspace(self)
        self.call_bridge = CallBridgeWorkspace(self)
        self.settings = SettingsWorkspace(self)

        self.setWindowTitle("lianiq")
        self.setMinimumSize(*MINIMUM_SIZE)
        self.resize(*DEFAULT_SIZE)
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
        # F9 always targets the active session, whichever workspace is shown.
        QShortcut(QKeySequence("F9"), self, activated=self.stop_active_session)
        for index in range(len(DEFAULT_ENTRIES)):
            QShortcut(
                QKeySequence(f"Ctrl+{index + 1}"),
                self,
                activated=lambda index=index: self.navigation.select_index(index),
            )

    def _build_ui(self) -> None:
        root = QWidget()
        row = QHBoxLayout(root)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        self.navigation = NavigationSidebar(DEFAULT_ENTRIES)
        row.addWidget(self.navigation)
        column = QVBoxLayout()
        column.setContentsMargins(20, 16, 20, 12)
        column.setSpacing(10)
        row.addLayout(column, 1)

        # The strip exists first: the held-turn bar returns focus to its **Stop**.
        self.session_strip = SessionStrip()
        self.session_strip.stop_button.clicked.connect(self.stop_active_session)
        self.pages = QStackedWidget()
        conversation_page = QWidget()
        conversation_page.setObjectName("conversationPage")
        conversation_layout = QVBoxLayout(conversation_page)
        conversation_layout.setContentsMargins(0, 0, 0, 0)
        conversation_layout.setSpacing(10)
        self.conversation.build(conversation_layout)
        self.workspace_pages = {
            WorkspaceId.CONVERSATION: conversation_page,
            WorkspaceId.CALL_BRIDGE: self.call_bridge.build_page(),
            WorkspaceId.SETTINGS: self.settings.build_page(),
        }
        for page in self.workspace_pages.values():
            self.pages.addWidget(page)
        column.addWidget(self.pages, 1)
        column.addWidget(self.session_strip)
        self.navigation.workspace_selected.connect(self.show_workspace)
        self.navigation.select(WorkspaceId.CONVERSATION, notify=False)
        self.session_owner.subscribe(self._session_changed)

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
            QFrame#navigationSidebar { background: #0b1220; border-right: 1px solid #334155; }
            QFrame#navigationSidebar QToolButton { padding: 8px; border-radius: 7px;
                                                   text-align: left; }
            QFrame#navigationSidebar QToolButton:checked { background: #1e293b;
                                                           border-left: 3px solid #60a5fa;
                                                           font-weight: 700; }
            QFrame#navigationSidebar QToolButton:disabled { color: #64748b; }
            QFrame#sessionStrip { background: #1e293b; border: 1px solid #475569;
                                  border-radius: 7px; }
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

    # The shell.

    @Slot(object)
    def show_workspace(self, workspace: WorkspaceId) -> bool:
        """Show ``workspace``'s page; ``False`` for a planned entry (no page)."""
        page = self.workspace_pages.get(workspace)
        if page is None:
            return False
        if self.navigation.current() is not workspace:
            self.navigation.select(workspace, notify=False)
        if workspace is WorkspaceId.SETTINGS:
            self.settings.refresh()
        self.pages.setCurrentWidget(page)
        return True

    def current_workspace(self) -> WorkspaceId:
        current = self.pages.currentWidget()
        return next(key for key, page in self.workspace_pages.items() if page is current)

    @Slot()
    def stop_active_session(self) -> None:
        """**Stop (F9)**: stop whichever mode holds the session; idle, stop the conversation."""
        if self.session_owner.state is SessionState.IDLE:
            self.stop_listening()  # as before the shell: F9 also clears a stopped conversation
        else:
            self.session_owner.stop()

    def _session_changed(self, state: SessionState, active: WorkspaceId | None) -> None:
        self.session_strip.show_state(state, active)
        self.navigation.set_session_owner(None if state is SessionState.IDLE else active)

    def resizeEvent(self, event: QResizeEvent) -> None:
        # Below 1000 logical px the sidebar collapses to the icon rail (spec §2.3.1).
        self.navigation.fit_window_width(event.size().width())
        super().resizeEvent(event)

    # Shared by the workspaces.

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
