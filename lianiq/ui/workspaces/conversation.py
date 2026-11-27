"""The Conversation workspace: pair, direction, devices, capture and results (CAP-0168 WI-01).

Moved behaviour-neutrally out of ``ui/main_window.py``. The workspace owns its controls and
the conversation session (capture, runner, ``SessionController``); ``MainWindow`` composes it
with the Call Bridge and Settings workspaces and provides the shared status bar, session lock,
model warm-up and the active-session owner. Accessible names and the held-turn focus return
are set on the widgets here (CAP-0169 WI-08 DEF-04/DEF-05, formerly ``ui/accessibility.py``).

CAP-0168 WI-02 (RES-06): one compact row of controls, then the held-turn bar and the paired
transcript view filling the rest (paired-transcript WI-02). Model profile, compute device and the
hardware subtitle moved to Settings › Diagnostics; **Stop (F9)** is in the session strip. A
start goes through ``ActiveSessionOwner.request_start``, so it is refused while the Call
Bridge holds the session; then **Start** is disabled with the ``SESSION_BUSY`` tooltip.

CAP-0168 WI-03: failures are notices (``ConversationNotices``), not status-bar text; the
status bar keeps the readiness and progress lines.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Signal, Slot

from lianiq.audio.capture import MicrophoneCapture
from lianiq.audio.playback import stop_playback
from lianiq.config_voice import VoicePreferences
from lianiq.conversation.routing import HeldTurn
from lianiq.conversation.spoken_output import PlaybackState, SpokenOutput
from lianiq.languages.modes import SessionPair
from lianiq.languages.registry import LanguageId
from lianiq.languages.session import SessionController
from lianiq.pipeline import PipelineRunner
from lianiq.transcript.turns import TurnLog
from lianiq.ui.shell.workspaces import WorkspaceId

# CAP-0168 file-size split: the controls, the pair and availability logic and Start/Stop
# moved to these bases. The capture and runner construction stay here, so the names tests
# and scripts patch on this module are still looked up here. The device selectors moved
# to Settings › Audio devices (``ui/device_setup.py``, WI-04).
from lianiq.ui.workspaces.conversation_availability import ConversationAvailability
from lianiq.ui.workspaces.conversation_flow import ConversationFlow
from lianiq.ui.workspaces.conversation_layout import ConversationLayout
from lianiq.ui.workspaces.conversation_notices import ConversationNotices
from lianiq.ui.workspaces.conversation_status import ConversationStatus
from lianiq.ui.workspaces.conversation_transcript import ConversationTranscript
from lianiq.ui.workspaces.conversation_voice import ConversationVoice
from lianiq.ui.workspaces.pair_selection import PairSelection

if TYPE_CHECKING:
    from lianiq.ui.main_window import MainWindow


class ConversationWorkspace(
    ConversationLayout,
    ConversationTranscript,
    ConversationAvailability,
    ConversationVoice,
    ConversationStatus,
    ConversationFlow,
    QObject,
):
    # The voice rows changed their statuses, switches or lock (Settings mirrors them).
    voice_rows_changed = Signal()

    def __init__(self, host: MainWindow) -> None:
        super().__init__(host)
        self.host = host
        self.config = host.config
        self.pipeline = host.pipeline
        self.voice_preferences = VoicePreferences(self.config, self.pipeline.registry)
        bridge = host.bridge
        bridge.result.connect(self._show_result)
        bridge.held.connect(self._show_held)
        bridge.held_resolved.connect(self._held_resolved)
        bridge.busy.connect(self._show_busy)
        bridge.level.connect(self._show_level)
        bridge.playback_state.connect(self._show_playback_state)
        bridge.session_ready.connect(self._session_ready)
        self.notices = ConversationNotices(self)
        bridge.pipeline_event.connect(self._pipeline_event)
        # Completed turns, in memory only, by capture time; exported as transcript v2.
        self.turns = TurnLog()
        # Models are constructed and warmed on Start, for the started mode only.
        self.starting = False
        self.translating = False
        self._pending_session: SessionPair | None = None
        self.diagnostic_wav: Path | None = None
        self.owner = host.session_owner
        self._generation = 0  # the owner generation of this workspace's latest start
        self.owner.register(WorkspaceId.CONVERSATION, self.stop_listening, asynchronous=True)
        self.connect_status()  # sticky errors and the stop thread's report (WI-02)
        self.owner.subscribe(self._session_changed)
        self.owner.subscribe(self._voice_session_changed)  # Voice options… locks (WI-05)
        self.pairs = PairSelection(
            self.config, self.pipeline.registry, lambda: self.session_controller.catalog
        )

    def start_session_services(self) -> None:
        """Capture, runner and the session gate, after the controls exist."""
        bridge = self.host.bridge
        self.capture = MicrophoneCapture(
            self.config.audio,
            on_utterance=self._submit_audio,
            on_level=bridge.level.emit,
            on_error=lambda message: bridge.error.emit(message, self.live_generation),
        )

        # Overflow, dropped turns and playback failure become notices; each event carries
        # the generation of the session that produced it (``live_generation``, WI-02).
        def emit_event(event) -> None:
            bridge.pipeline_event.emit(event, self.live_generation)

        def emit_spoken_event(event) -> None:
            bridge.pipeline_event.emit(event, self.spoken_generation())

        self.pipeline.on_event = emit_event
        # CAP-0167 WI-02: each result is spoken after it is shown; capture is muted while
        # a translation is synthesized and played (the former ``_translate`` mute window),
        # and the UI shows the pause through ``UiBridge.playback_state`` (WI-04).
        self.pipeline.spoken = SpokenOutput(
            self.pipeline.voice_synthesizer,
            lambda path, device: self.pipeline.playback(path, device),
            lambda: stop_playback(),  # looked up here, so tests patch this module's name
            self.voice_preferences.options,
            self.on_playback_state,
            emit_spoken_event,
        )
        self.replayer.attach(self.pipeline.spoken)  # per-turn Replay (paired-transcript WI-03)
        self.runner = PipelineRunner(
            self.pipeline,
            # Every signal carries the generation of the session that produced it.
            on_result=lambda result: bridge.result.emit(result, self.live_generation),
            on_error=lambda message: bridge.error.emit(message, self.live_generation),
            on_busy=lambda busy: bridge.busy.emit(busy, self.live_generation),
            on_held=lambda held: bridge.held.emit(held, self.live_generation),
            on_event=emit_event,
        )
        # The session gate checks the mode's models and the resolved audio devices.
        self.session_controller = SessionController(
            self.pipeline,
            self.runner,
            devices=self.device_readiness,
            capture=self.capture,
        )

    @Slot(int, bool, str)
    def _session_ready(self, generation: int, ready: bool, message: str) -> None:
        if not self.starting or generation != self.host.start_generation:
            return  # This Start was stopped or superseded while its models were loading.
        self.starting = False
        session, self._pending_session = self._pending_session, None
        # The spoken plan is bound at Start: ``prepare`` warmed and bound its voices.
        if not ready or session is None:
            self.diagnostic_wav = None
            self.owner.mark_idle(self._generation)
            self.start_button.setEnabled(True)
            self.set_session_controls_enabled(True)
            self.idle_text = "Model error"
            self.show_activity()
            self.notices.model_failed(message)
            return
        self._begin_listening(session)
        path, self.diagnostic_wav = self.diagnostic_wav, None
        if path is not None and self.capture.running:
            threading.Thread(
                target=self._submit_diagnostic_wav,
                args=(path,),
                name="diagnostic-wav-input",
                daemon=True,
            ).start()

    def _submit_audio(self, utterance) -> None:
        self.runner.submit(utterance)

    @Slot(object, int)
    def _show_held(self, _held: HeldTurn, generation: int) -> None:
        # Nothing is translated until the user resolves the turn in the held-turn bar.
        if self.current(generation):
            self._refresh_held_bar()

    def _refresh_held_bar(self) -> None:
        if self.held_turn_bar.resolving:
            return  # refreshed when the running resolution reports back
        session = self.session_controller.session
        if self.session_controller.running and session is not None:
            self.held_turn_bar.set_held(self.pipeline.held_turns(), session.pair)
        else:
            self.held_turn_bar.clear()

    @Slot(object, str)
    def _resolve_held(self, held: HeldTurn, language: str) -> None:
        """Re-recognise the held turn as the chosen language; its row lands at capture time."""
        self.held_turn_bar.set_resolving(True)
        generation = self.live_generation
        bridge = self.host.bridge
        self.runner.resolve(
            held, LanguageId(language), on_done=lambda: bridge.held_resolved.emit(generation)
        )

    @Slot(int)
    def _held_resolved(self, generation: int) -> None:
        if not self.current(generation):
            return  # the stop cleared the bar of that session
        self.held_turn_bar.set_resolving(False)
        self._refresh_held_bar()

    @Slot(object)
    def _discard_held(self, held: HeldTurn) -> None:
        """Drop the held turn and its audio: no result, no history, no export line."""
        self.pipeline.discard(held)
        self._refresh_held_bar()

    @Slot(bool, int)
    def _show_busy(self, busy: bool, generation: int) -> None:
        if self.current(generation):
            self.translating = busy
            self.show_activity()  # the microphone pause and a sticky error stay shown

    @Slot(object, int)
    def _pipeline_event(self, event, generation: int) -> None:
        if self.current(generation):
            self.notices.pipeline_event(event, generation)

    @Slot(float)
    def _show_level(self, level: float) -> None:
        if self.playback_state is PlaybackState.IDLE:  # a muted capture's late level: ignored
            self.level_bar.setValue(round(level * 100))
