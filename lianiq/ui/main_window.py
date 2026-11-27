"""The main window: the desktop shell over the workspaces (CAP-0168 WI-01, WI-02).

The workspaces own their controls and logic (``ui/workspaces/``). The window keeps what they
share: the signal hand-off from worker threads (``UiBridge``), the status bar, the session
lock, the model warm-up generation and saving on close. Accessor properties keep the
established ``MainWindow`` attribute paths for scripts and tests.

WI-02 shell (spec §2.3.1-§2.3.2): the navigation sidebar on the left, the workspace pages in
a ``QStackedWidget`` and the session strip with **Stop (F9)** below them. The one
``ActiveSessionOwner`` allows one session across modes; F9 stops the active session from
every workspace; Ctrl+1…Ctrl+7 select the enabled sidebar entries by position. Showing a
page never starts or stops capture or playback. CAP-0177 adds the Meeting workspace, second;
its controller is built at Start by ``meeting_factory`` (registered by ``lianiq.app``).

WI-03 notices (spec §2.3.4): failures are persistent notices in the ``NoticeCenter``, shown
by a ``NoticeBanner`` at the top of each workspace; the status bar only shows progress. Every
notice change is recorded in the local ``DiagnosticsLog`` (Settings › Diagnostics).

WI-05 presentation (spec §2.3.7): ``theme.py`` styles the window; workspace content scrolls
with Start/Stop and the strip outside it; Tab runs sidebar → workspace → strip.

session-status-truthfulness WI-01: F8 starts the shown page's mode and F9 only stops the
active session (``shell/start_dispatch.py``, which also binds the shortcuts).
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Slot
from PySide6.QtGui import QCloseEvent, QResizeEvent
from PySide6.QtWidgets import QMainWindow

from lianiq.config import AppConfig
from lianiq.diagnostics import DiagnosticsLog
from lianiq.languages.modes import SessionPair
from lianiq.pipeline import TranslationPipeline
from lianiq.ui import notice_catalog as catalog
from lianiq.ui import theme
from lianiq.ui.device_setup import DeviceSetup
from lianiq.ui.main_window_layout import MainWindowLayout
from lianiq.ui.main_window_services import MainWindowServices
from lianiq.ui.notices import NoticeCenter
from lianiq.ui.shell import start_dispatch
from lianiq.ui.shell.session_owner import ActiveSessionOwner
from lianiq.ui.shell.workspaces import WorkspaceId
from lianiq.ui.ui_bridge import UiBridge
from lianiq.ui.workspaces.call_bridge import CallBridgeWorkspace
from lianiq.ui.workspaces.conversation import ConversationWorkspace
from lianiq.ui.workspaces.language_packs import LanguagePacksWorkspace
from lianiq.ui.workspaces.meeting import MeetingWorkspace
from lianiq.ui.workspaces.settings import SettingsWorkspace

DEFAULT_SIZE = (1280, 720)
MINIMUM_SIZE = (850, 560)


def _forward(workspace: str, name: str) -> property:
    """A ``MainWindow`` attribute that reads and writes ``workspace.name``."""
    return property(
        lambda self: getattr(getattr(self, workspace), name),
        lambda self, value: setattr(getattr(self, workspace), name, value),
    )


class MainWindow(MainWindowLayout, MainWindowServices, QMainWindow):
    default_size, minimum_size = DEFAULT_SIZE, MINIMUM_SIZE  # ``fit_to_work_area``
    # Conversation workspace.
    history = _forward("conversation", "history")
    capture = _forward("conversation", "capture")
    runner = _forward("conversation", "runner")
    session_controller = _forward("conversation", "session_controller")
    pair_combo = _forward("conversation", "pair_combo")
    mode_combo = _forward("conversation", "mode_combo")
    voice_rows = _forward("conversation", "voice_rows")
    start_button = _forward("conversation", "start_button")
    # Session strip: **Stop (F9)** stops the active session from every workspace.
    stop_button = _forward("session_strip", "stop_button")
    swap_button = _forward("conversation", "swap_button")
    held_turn_bar = _forward("conversation", "held_turn_bar")
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
        meeting_factory=None,
    ) -> None:
        super().__init__()
        self.config = config
        self.pipeline = pipeline
        self.persist_settings = persist_settings
        self.meeting_factory = meeting_factory  # builds the MeetingController at Start
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
        self.meeting = MeetingWorkspace(self)
        self.settings = SettingsWorkspace(self)
        self.language_packs = LanguagePacksWorkspace(self)
        self.device_setup = DeviceSetup(self)

        self.setWindowTitle("lianiq")
        self.setMinimumSize(*MINIMUM_SIZE)
        self.resize(*DEFAULT_SIZE)
        self._build_ui()
        self._load_devices()
        # WI-05: tokens, fonts and focus outline; none of it in Windows high contrast.
        theme.apply(self)
        theme.follow_system(self)

        self.conversation.start_session_services()
        self.listen.attach_spoken(self.pipeline.spoken)  # Listen's Replay (paired-transcript)
        self.call_bridge_panel.set_models_ready(True)
        self.conversation.connect_selection()
        self.meeting.connect_selection()
        start_dispatch.install_shortcuts(self)  # F8, F9, Ctrl+1…7; diagnostic starts

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
        elif workspace is WorkspaceId.MEETING:
            self.meeting.refresh()
        elif workspace is WorkspaceId.LANGUAGE_PACKS:
            self.language_packs.refresh()
        self.pages.setCurrentWidget(page)
        return True

    def current_workspace(self) -> WorkspaceId:
        current = self.pages.currentWidget()
        return next(key for key, page in self.workspace_pages.items() if page is current)

    @Slot()
    def stop_active_session(self) -> None:
        """**Stop (F9)**: stop whichever mode holds the session; while idle nothing happens."""
        start_dispatch.stop_active_session(self)

    @Slot()
    def start_current_page(self) -> None:
        """**F8**: start the shown page's mode (``start_dispatch``)."""
        start_dispatch.start_current_page(self)

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
        """Start Conversation (scripts, ``--diagnostic-auto-start`` and tests)."""
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
        self.meeting.end_meeting()  # drains on its own thread; never blocks the close
        self.text_translation.shutdown()
        self.listen.shutdown()
        self.stop_call_bridge()
        self.stop_listening()
        if self.persist_settings:
            self.call_bridge_panel.apply_to_config()
            self.conversation.save_routing()
            # ``tts.output`` holds the voice switches; ``languages.output`` mirrors the plan.
            self.config.save()
        event.accept()
