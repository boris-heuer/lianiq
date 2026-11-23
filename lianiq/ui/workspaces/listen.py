"""The Listen & translate workspace (CAP-0170 WI-03): speech in one language, text out.

Sidebar entry *Listen & translate*, fourth (Ctrl+4). Showing the page opens nothing; **Start
listening (F8)** runs the ``ListenController`` start gate, loads only the recogniser and the
translator and opens the chosen microphone. Rows appear in capture order with their state;
no voice is ever built or played. The selectors are locked while not idle. Worker callbacks
reach the GUI thread through the queued ``posted`` signal. Choices go to ``config.listen``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, QObject, Signal, Slot

from lianiq.audio.capture import MicrophoneCapture
from lianiq.languages.modes import SessionPair
from lianiq.languages.requirements import ModeAvailability, RequirementKind
from lianiq.listen.controller import ListenController
from lianiq.listen.lifecycle import LISTEN, AlertKind, ListenAlert, ListenPhase, ListenSnapshot
from lianiq.listen.pipeline import ListenPipeline
from lianiq.listen.session import ListenReadiness, StartBlock, listen_readiness
from lianiq.ui import notice_catalog as catalog
from lianiq.ui import strings
from lianiq.ui.notice_catalog_base import model_failed_key
from lianiq.ui.shell.session_owner import SessionBusy
from lianiq.ui.shell.workspaces import WorkspaceId, session_busy_message
from lianiq.ui.workspaces.listen_actions import ListenTranscriptActions
from lianiq.ui.workspaces.listen_layout import ListenLayout
from lianiq.ui.workspaces.listen_model import ListenTranscriptModel, reason_text
from lianiq.ui.workspaces.listen_selection import ListenSelection

if TYPE_CHECKING:
    from lianiq.ui.main_window import MainWindow

BUSY_STATES = {
    ListenPhase.LOADING: strings.LISTEN_STATE_LOADING,
    ListenPhase.STOPPING: strings.LISTEN_STATE_STOPPING,
}


class ListenWorkspace(ListenTranscriptActions, ListenSelection, ListenLayout, QObject):
    posted = Signal(object)  # a worker callback, run on the GUI thread
    level = Signal(float)  # the microphone level, from the audio thread

    def __init__(self, host: MainWindow) -> None:
        super().__init__(host)
        self.host = host
        self.registry = host.pipeline.registry
        self.config = host.config.listen
        self.posted.connect(self._run_posted)  # queued: the receiver lives on the GUI thread
        self.level.connect(self._show_level)
        self.pipeline = ListenPipeline(host.pipeline)
        self.controller = ListenController(
            host.session_owner,
            host.usage_tracker,  # the one tracker of the session's packs (CAP-0171)
            self.pipeline,
            self._capture,
            self.microphone,
            self.posted.emit,
            self.render,
            self.notify,
            self.readiness,
        )
        self.source, self.target = self._defaults()
        self._phase = ListenPhase.IDLE
        self._stopped = self._error = False

    def readiness(self, session: SessionPair) -> ListenReadiness:
        owner = self.host.session_owner
        return listen_readiness(
            session,
            self.host.pipeline.catalog,
            self.host.language_packs.packs,
            self.microphone(),
            owner.busy_for(LISTEN),
        )

    def _capture(self, on_utterance, on_error) -> MicrophoneCapture:
        return MicrophoneCapture(
            self.host.config.audio,
            on_utterance=on_utterance,
            on_level=self.level.emit,
            on_error=on_error,
        )

    def active(self) -> bool:
        return self.controller.phase is not ListenPhase.IDLE

    # Page.

    def build_page(self):
        page = super().build_page()
        self.model = ListenTranscriptModel(self.controller.transcript, self.registry)
        self.transcript_view.setModel(self.model)
        self.source_combo.activated.connect(lambda _i: self._language_chosen(self.source_combo))
        self.target_combo.activated.connect(lambda _i: self._language_chosen(self.target_combo))
        self.swap_button.clicked.connect(self._swap)
        self.microphone_combo.activated.connect(self._microphone_chosen)
        self.start_button.clicked.connect(self.start)
        self.open_packs_button.clicked.connect(
            lambda: self.host.show_workspace(WorkspaceId.LANGUAGE_PACKS)
        )
        self.open_audio_button.clicked.connect(self.open_audio_settings)
        self.connect_actions()
        page.installEventFilter(self)
        self._sync_combos()
        self.refresh()
        return page

    def eventFilter(self, watched, event) -> bool:
        if watched is getattr(self, "page", None) and event.type() == QEvent.Type.Show:
            self.refresh()  # devices or packs may have changed elsewhere
            if not self.source_combo.hasFocus() and self.host.focusWidget() is None:
                self.source_combo.setFocus()
        return False

    def refresh(self) -> None:
        if not self.active():
            self.load_microphones()
        session = self.session()
        if session is not None:
            self.controller.select(session)
        else:
            self.controller.render()

    def open_audio_settings(self) -> None:
        """Settings › Audio devices with the Conversation microphone selector focused."""
        self.host.show_workspace(WorkspaceId.SETTINGS)
        self.host.device_setup.input_combo.setFocus()

    # Session.

    def start(self) -> None:
        """**Start listening (F8)**; a start while another mode runs is refused with a notice."""
        session = self.session()
        if session is None or self.active():
            return
        owner = self.host.session_owner
        if (other := owner.busy_for(LISTEN)) is not None:
            self.host.show_busy(LISTEN, other)
            return
        self.host.resolve_notices((model_failed_key(LISTEN),))
        try:
            self.controller.start(session)
        except SessionBusy as busy:
            self.host.show_busy(LISTEN, busy.active)

    def shutdown(self) -> None:
        self.controller.shutdown()

    def notify(self, alert: ListenAlert) -> None:
        where = catalog.source(LISTEN)
        if alert.kind is AlertKind.START_FAILED:
            self._error = True
            self.state_label.setText(strings.LISTEN_STATE_MODEL_ERROR)
            reason = reason_text(alert.reason)
            self.host.post_notice(catalog.model_failed(LISTEN, reason, where, self.start))
        else:  # **Reconnect** and **Choose device**: WI-05
            text = strings.LISTEN_MIC_LOST.format(device=alert.device_name)
            self.host.post_notice(catalog.error(LISTEN, text, where))

    @Slot(object)
    def _run_posted(self, callback) -> None:
        callback()

    @Slot(float)
    def _show_level(self, level: float) -> None:
        if self._phase is ListenPhase.LISTENING:
            self.level_bar.setValue(round(level * 100))

    # Rendering.

    def render(self, snapshot: ListenSnapshot) -> None:
        if not hasattr(self, "model"):
            return
        phase, idle = snapshot.phase, snapshot.phase is ListenPhase.IDLE
        if not idle:
            self._error = False
        elif self._phase is not ListenPhase.IDLE:
            self._stopped = True
        self._phase = phase
        self.follow(snapshot)
        for widget in (self.source_combo, self.target_combo, self.swap_button):
            widget.setEnabled(idle)
            widget.setToolTip("" if idle else strings.LISTEN_LOCKED)
        self.microphone_combo.setEnabled(idle)
        self.microphone_combo.setToolTip(
            self.microphone_combo.currentText() if idle else strings.LISTEN_LOCKED
        )
        self.state_label.setText(self._state_text(snapshot))
        if phase is not ListenPhase.LISTENING:
            self.level_bar.setValue(0)
        session = self.session()
        block = snapshot.readiness.block if session is not None else StartBlock.UNSUPPORTED
        self.readiness_label.setText(
            self._readiness_text(block, snapshot.readiness) if idle else ""
        )
        self.readiness_label.setVisible(bool(self.readiness_label.text()))
        self.start_button.setEnabled(idle and session is not None and block is StartBlock.NONE)
        active = self.host.session_owner.active
        busy = block is StartBlock.BUSY and active is not None
        self.start_button.setToolTip(session_busy_message(active) if busy else "")
        no_packs = idle and not self.controller.transcript.rows and self._no_packs()
        self.open_packs_button.setVisible(idle and (block is StartBlock.PACK_MISSING or no_packs))
        self.open_audio_button.setVisible(idle and block is StartBlock.MICROPHONE_MISSING)
        if self.controller.transcript.rows:
            empty = ""
        elif phase is ListenPhase.LISTENING:
            empty = strings.LISTEN_WAITING
        else:
            empty = strings.LISTEN_NO_PACK_HINT if no_packs else strings.LISTEN_EMPTY
        self.empty_label.setText(empty)
        self.empty_label.setVisible(bool(empty))

    def _state_text(self, snapshot: ListenSnapshot) -> str:
        if snapshot.phase is ListenPhase.LISTENING:
            busy = snapshot.busy
            return strings.LISTEN_STATE_PROCESSING if busy else strings.LISTEN_STATE_LISTENING
        if snapshot.phase is not ListenPhase.IDLE:
            return BUSY_STATES[snapshot.phase]
        if self._error:
            return strings.LISTEN_STATE_MODEL_ERROR
        return strings.LISTEN_STATE_STOPPED if self._stopped else strings.LISTEN_STATE_READY

    def _readiness_text(self, block: StartBlock, readiness: ListenReadiness) -> str:
        if block is StartBlock.UNSUPPORTED:
            return strings.LISTEN_UNSUPPORTED.format(
                source=self.registry.display_name(self.source),
                target=self.registry.display_name(self.target),
            )
        if block is StartBlock.PACK_MISSING:
            models = tuple(
                item for item in readiness.missing if item.kind is not RequirementKind.MICROPHONE
            )
            return self.host.describe_missing(ModeAvailability(False, models))
        if block is StartBlock.MICROPHONE_MISSING:
            return strings.LISTEN_MIC_MISSING
        return ""
