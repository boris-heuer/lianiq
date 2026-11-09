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

WI-03 notices (spec §2.3.4): failures are persistent notices in the ``NoticeCenter``, shown
by a ``NoticeBanner`` at the top of each workspace; the status bar only shows progress. Every
notice change is recorded in the local ``DiagnosticsLog`` (Settings › Diagnostics).
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal, Slot
from PySide6.QtGui import QCloseEvent, QKeySequence, QResizeEvent, QShortcut
from PySide6.QtWidgets import QMainWindow

from lianiq.config import AppConfig
from lianiq.diagnostics import DiagnosticsLog
from lianiq.languages.modes import SessionPair
from lianiq.pipeline import TranslationPipeline
from lianiq.ui import notice_catalog as catalog
from lianiq.ui.device_setup import DeviceSetup
from lianiq.ui.main_window_layout import MainWindowLayout
from lianiq.ui.main_window_services import MainWindowServices
from lianiq.ui.notices import NoticeCenter
from lianiq.ui.shell.session_owner import ActiveSessionOwner, SessionState
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
    pipeline_event = Signal(object, int)  # PipelineEvent, session generation


def _forward(workspace: str, name: str) -> property:
    """A ``MainWindow`` attribute that reads and writes ``workspace.name``."""
    return property(
        lambda self: getattr(getattr(self, workspace), name),
        lambda self, value: setattr(getattr(self, workspace), name, value),
    )


class MainWindow(MainWindowLayout, MainWindowServices, QMainWindow):
    # Conversation workspace.
    history = _forward("conversation", "history")
    capture = _forward("conversation", "capture")
    runner = _forward("conversation", "runner")
    session_controller = _forward("conversation", "session_controller")
    pair_combo = _forward("conversation", "pair_combo")
    mode_combo = _forward("conversation", "mode_combo")
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
    # Settings › Audio devices: the Conversation devices by endpoint identity (WI-04).
    devices = _forward("device_setup", "devices")
    input_combo = _forward("device_setup", "input_combo")
    output_combo = _forward("device_setup", "output_combo")
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
        self.notices = NoticeCenter()
        self.diagnostics = DiagnosticsLog()
        self.notices.subscribe(self._notice_changed)
        # Each Start gets a generation; a ready signal of a cancelled Start is ignored.
        self.start_generation = 0
        self.session_owner = ActiveSessionOwner()
        self.conversation = ConversationWorkspace(self)
        self.call_bridge = CallBridgeWorkspace(self)
        self.settings = SettingsWorkspace(self)
        self.device_setup = DeviceSetup(self)

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

    @Slot()
    def show_diagnostics(self) -> None:
        """Open Settings › Diagnostics with the notice history ("+N more")."""
        self.show_workspace(WorkspaceId.SETTINGS)
        self.settings.diagnostics_view.history_text.setFocus()

    def resizeEvent(self, event: QResizeEvent) -> None:
        # Below 1000 logical px the sidebar collapses to the icon rail (spec §2.3.1).
        self.navigation.fit_window_width(event.size().width())
        super().resizeEvent(event)

    @Slot(str)
    def show_error(self, message: str, workspace: WorkspaceId = WorkspaceId.CONVERSATION) -> None:
        """Any other failure: a warning notice in ``workspace`` (no longer the status bar)."""
        self.post_notice(catalog.error(workspace, message, self.notice_source(workspace)))
        if workspace is WorkspaceId.CONVERSATION:
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
