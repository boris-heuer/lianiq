"""The Conversation state line and its asynchronous Stop (session-status-truthfulness WI-02).

``ConversationWorkspace`` base (file-size split). ``activity_text`` is the one source of the
state line (spec §2.3): *Error — see notice* while a failure notice of a running or starting
session is open (sticky through busy, playback and availability updates), *Stopping…*,
*Loading models …*, the CAP-0167 microphone pause, *Translating …* / *Listening …* only while
capture is open, else the idle text: *Ready* on first launch, *Stopped · {n} turns kept* after
a session, *Stopped — {n} not finished* after a stop that timed out.

**Stop** is the owner's asynchronous stopper: on the GUI thread it shows *Stopping…* and
closes capture; ``SpokenOutput.close()`` and ``SessionController.stop()`` run on a
``conversation-stop`` thread, whose ``StopReport`` comes back through
``UiBridge.conversation_stopped``; then the owner is marked idle. A timed-out worker is
registered with ``owner.linger``, so the next Start is refused until it has exited.

Worker signals carry ``live_generation``: the session's owner generation from its start
until its stop has finished, then 0, so a late result, busy, held or error signal of an
ended session never shows. Spoken output (also a replay while idle) carries the latest
generation. The slots accept only ``current`` generations.
"""

from __future__ import annotations

import logging
import threading
import time

from PySide6.QtCore import QCoreApplication, QDeadlineTimer, QEventLoop, Slot

from lianiq.conversation.spoken_output import PlaybackState
from lianiq.languages.session import StopReport
from lianiq.ui import notice_catalog as catalog
from lianiq.ui import strings
from lianiq.ui import strings_session as session_strings
from lianiq.ui.shell.workspaces import WorkspaceId

LOGGER = logging.getLogger(__name__)
CONVERSATION = WorkspaceId.CONVERSATION
LOADING_TEXT = "Loading models …"


class ConversationStatus:
    """``ConversationWorkspace`` base: the state line, sticky errors and the stop thread."""

    stopping = False  # the ``conversation-stop`` thread runs
    idle_text = "Ready"  # the state while idle: *Ready* only before the first session
    live_generation = 0  # stamped on worker signals; 0 when no session is live

    def connect_status(self) -> None:
        self._sticky: set[str] = set()  # failure notice keys that hold *Error — see notice*
        bridge = self.host.bridge
        bridge.error.connect(self._show_error)
        bridge.conversation_stopped.connect(self._stop_finished)
        self.host.notices.subscribe(self._notice_changed)

    def current(self, generation: int) -> bool:
        """A signal of the latest session (a stale one of an ended session is dropped)."""
        return generation == self._generation

    def spoken_generation(self) -> int:
        """Spoken output: the live session's generation, else the latest (a replay)."""
        return self.live_generation or self._generation

    # The state line.

    def activity_text(self) -> str:
        if self.error_open():
            return session_strings.STATE_ERROR
        if self.stopping:
            return session_strings.STATE_STOPPING
        if self.starting:
            return LOADING_TEXT
        if self.playback_state is not PlaybackState.IDLE:
            return strings.VOICE_MIC_PAUSED
        capture = getattr(self, "capture", None)  # built after the controls
        if capture is None or not capture.running:
            return self.idle_text
        return "Translating …" if self.translating else "Listening …"

    def show_activity(self) -> None:
        self.state_label.setText(self.activity_text())

    def error_open(self) -> bool:
        return any(self.host.notices.get(key) is not None for key in self._sticky)

    def show_failure(self, key: str) -> None:
        """A failure notice ``key`` was posted: sticky *Error* while a session is active."""
        controller = getattr(self, "session_controller", None)  # built after the controls
        if self.starting or self.stopping or (controller is not None and controller.running):
            self._sticky.add(key)
            self.show_activity()

    @Slot(str, int)
    def _show_error(self, message: str, generation: int) -> None:
        if self.current(generation):
            self.host.show_error(message)

    def _notice_changed(self, change: str, notice) -> None:
        if change == "resolved" and notice.key in self._sticky:
            self._sticky.discard(notice.key)  # resolved or closed: the current activity
            self.show_activity()

    # Stop.

    @Slot()
    def stop_listening(self) -> None:
        """Stop the session: capture now, the drain on the ``conversation-stop`` thread."""
        if self.stopping:
            return
        generation, starting = self._generation, self.starting
        self.starting = False
        self._pending_session = None
        self.diagnostic_wav = None
        if not self.session_controller.running:
            # Stopped while its models load (or nothing runs): nothing to drain.
            if starting or self.owner.active is CONVERSATION:
                self._stopped(generation, StopReport(0, ()))
            return
        self.stopping = True
        self.level_bar.setValue(0)
        self.show_activity()
        try:
            self.capture.stop()  # no new turns; ``SessionController.stop`` repeats it
        except Exception:
            LOGGER.exception("Capture stop failed")
        threading.Thread(
            target=self._drain, args=(generation,), name="conversation-stop", daemon=True
        ).start()

    def _drain(self, generation: int) -> None:
        """The stop thread: nothing is spoken any more; queued turns finish as text."""
        spoken = self.pipeline.spoken
        try:
            if spoken is not None:
                spoken.close()
        except Exception:
            LOGGER.exception("Spoken output close failed")
        outcome: object
        try:
            outcome = self.session_controller.stop()
        except Exception as exc:
            LOGGER.exception("Conversation stop failed")
            outcome = exc
        if self.live_generation == generation:
            self.live_generation = 0  # a late signal of this session is dropped
        self.host.bridge.conversation_stopped.emit(generation, outcome)

    @Slot(int, object)
    def _stop_finished(self, generation: int, outcome: object) -> None:
        if generation == self._generation and self.stopping:
            self._stopped(generation, outcome)

    def _stopped(self, generation: int, outcome: object) -> None:
        self.stopping = self.translating = False
        self.playback_state = PlaybackState.IDLE
        self.held_turn_bar.set_resolving(False)
        self.held_turn_bar.clear()  # before **Start** is enabled: its focus return (DEF-05)
        report = outcome if isinstance(outcome, StopReport) else None
        if report is not None and report.timed_out:
            lost = report.not_finished
            self.idle_text = session_strings.counted(session_strings.STATE_STOPPED_LOSS, lost)
            self.owner.linger(CONVERSATION, report.alive)
            self.host.post_notice(catalog.stop_timeout(CONVERSATION, lost, generation))
        else:
            self.idle_text = session_strings.counted(session_strings.STATE_STOPPED, len(self.turns))
        if report is None:
            self.owner.linger(CONVERSATION, self.runner.alive)
            self.host.post_notice(catalog.stop_failed(CONVERSATION))
        if self.owner.active is CONVERSATION:
            self.owner.mark_idle(generation)
        call_bridge = self.host.call_bridge
        self.start_button.setEnabled(not call_bridge.active())
        self.set_devices_enabled(True)
        self.set_session_controls_enabled(call_bridge.controller is None)
        self.level_bar.setValue(0)
        self.show_activity()
        self.host.statusBar().showMessage("Capture stopped")
        self.refresh_playback()  # ``close`` cleared the last spoken translation (AC-12)
        self.notices.stopped(0 if report is None else len(report.discarded))

    def wait_stopped(self, timeout: float | None = None) -> bool:
        """Process events until the stop has finished (scripts, tests, ``MainWindow``)."""
        bound = self.session_controller.flush_timeout + 2.0 if timeout is None else timeout
        deadline = QDeadlineTimer(int(bound * 1000))
        while self.stopping and not deadline.hasExpired():
            QCoreApplication.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)
            time.sleep(0.005)
        return not self.stopping
