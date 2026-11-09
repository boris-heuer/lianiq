"""Start, Stop and transcript of ``ConversationWorkspace`` (CAP-0168 file-size split)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Slot

from lianiq.audio.wav import read_pcm16_mono
from lianiq.call_bridge.contracts import EndpointFlow
from lianiq.languages.errors import ModeUnavailableError
from lianiq.languages.modes import SessionPair
from lianiq.languages.session import format_transcript_v2
from lianiq.ui.shell.session_owner import SessionBusy, SessionState
from lianiq.ui.shell.workspaces import WorkspaceId, session_busy_message


class ConversationFlow:
    """``ConversationWorkspace`` base: Start and Stop of the session and the transcript."""

    def _submit_diagnostic_wav(self, path: Path) -> None:
        try:
            utterance = read_pcm16_mono(path, self.config.audio.sample_rate)
            self.runner.submit(utterance)
        except Exception as exc:  # noqa: BLE001 - diagnostic boundary reports all failures.
            self.host.bridge.error.emit(f"Diagnostic WAV failed: {exc}")

    @Slot()
    def start_listening(self) -> None:
        if self.starting or self.capture.running:
            return
        busy = self.owner.busy_for(WorkspaceId.CONVERSATION)
        if busy is not None:
            self.host.show_busy(WorkspaceId.CONVERSATION, busy)
            return
        try:
            session = self.session_pair()
            availability = self.session_controller.availability(session)
        except Exception as exc:  # noqa: BLE001 - GUI boundary reports invalid selections.
            self.host.show_error(str(exc))
            return
        # A saved device that is missing or unusable refuses Start; no other device is
        # chosen instead (spec §2.2.4).
        if self.host.device_setup.refuse_start(self.tts_checkbox.isChecked()):
            self.diagnostic_wav = None
            return
        if not availability.available:
            self.diagnostic_wav = None
            self.host.show_unavailable(availability.missing)
            return
        try:
            self._generation = self.owner.request_start(WorkspaceId.CONVERSATION)
        except SessionBusy as busy:
            self.host.show_busy(WorkspaceId.CONVERSATION, busy.active)
            return
        self.starting = True
        self._pending_session = session
        self.set_session_controls_enabled(False)
        self.start_button.setEnabled(False)
        self.state_label.setText("Loading models …")
        self.host.statusBar().showMessage("Loading the models the selected mode requires …")
        self.host.prepare_in_background(session, self.host.bridge.session_ready)

    def _begin_listening(self, session: SessionPair) -> None:
        try:
            # Open the resolved endpoints by runtime index (contract §4 "Opening").
            setup = self.host.device_setup
            microphone = setup.resolved(EndpointFlow.CAPTURE).endpoint
            speakers = setup.resolved(EndpointFlow.RENDER).endpoint
            self.capture.device = None if microphone is None else microphone.runtime_index
            self.pipeline.output_device = None if speakers is None else speakers.runtime_index
            self.session_controller.start(session)
        except ModeUnavailableError as exc:
            self.owner.mark_idle(self._generation)
            self.start_button.setEnabled(True)
            self.set_session_controls_enabled(True)
            self.host.show_unavailable(exc.missing)
            return
        except Exception as exc:  # noqa: BLE001 - GUI boundary reports dependency/device failures.
            self.owner.mark_idle(self._generation)
            self.start_button.setEnabled(True)
            self.set_session_controls_enabled(True)
            self.notices.start_failed(str(exc))
            return
        self.host.device_setup.session_started()
        self.owner.mark_running(self._generation)
        self.notices.running()
        self.start_button.setEnabled(False)
        self.set_devices_enabled(False)
        self.state_label.setText("Listening …")
        self.host.statusBar().showMessage("Offline capture is active")

    @Slot()
    def stop_listening(self) -> None:
        self.starting = False
        self._pending_session = None
        self.diagnostic_wav = None
        # Queued turns finish with their bound pair; unresolved held turns are discarded.
        report = self.session_controller.stop()
        self.held_turn_bar.clear()
        if self.owner.active is WorkspaceId.CONVERSATION:
            self.owner.mark_idle(self._generation)
        call_bridge = self.host.call_bridge
        self.start_button.setEnabled(not call_bridge.active())
        self.set_devices_enabled(True)
        self.set_session_controls_enabled(call_bridge.controller is None)
        self.level_bar.setValue(0)
        self.state_label.setText("Ready")
        self.host.statusBar().showMessage("Capture stopped")
        self.notices.stopped(len(report.discarded))

    def _session_changed(self, state: SessionState, active: WorkspaceId | None) -> None:
        """While another mode holds the session, **Start** says why it is disabled."""
        busy = state is not SessionState.IDLE and active is not WorkspaceId.CONVERSATION
        if busy and active is not None:
            self.start_button.setEnabled(False)
            self.start_button.setToolTip(session_busy_message(active))
        else:
            self.start_button.setToolTip("")

    def write_transcript(self, path: Path) -> None:
        """Write the in-memory history as transcript v2 (UTF-8), ordered by capture time."""
        session = self.session_controller.session
        pair = session.pair if session is not None else self.current_pair()
        if pair is None:
            pair = self.pipeline.registry.pair(*self.config.languages.pair)
        Path(path).write_text(format_transcript_v2(pair, self.history), encoding="utf-8")

    def save_routing(self) -> None:
        """Keep the selected routing in the settings when the window closes."""
        # Without a ready pair the routing control is empty: the migrated or saved
        # routing is kept, never replaced by Automatic (E-09, WI-08 DEF-01).
        if self.current_pair() is not None:
            fixed_source = self.current_fixed_source()
            self.config.languages.routing = "bidirectional" if fixed_source is None else "fixed"
            self.config.languages.fixed_source = fixed_source
