"""The Conversation workspace: pair, direction, devices, capture and results (CAP-0168 WI-01).

Moved behaviour-neutrally out of ``ui/main_window.py``. The workspace owns its controls and
the conversation session (capture, runner, ``SessionController``); ``MainWindow`` composes it
with the Call Bridge and Settings workspaces and provides the shared status bar, session lock,
model warm-up and the active-session owner. Accessible names and the held-turn focus return
are set on the widgets here (CAP-0169 WI-08 DEF-04/DEF-05, formerly ``ui/accessibility.py``).

CAP-0168 WI-02 (RES-06): one compact row of controls, then the held-turn bar and the
*Original*/*Translation* splitter filling the rest. Model profile, compute device and the
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
from lianiq.audio.devices import AudioDevice, list_audio_devices
from lianiq.conversation.routing import HeldTurn
from lianiq.domain import TranslationResult
from lianiq.languages.modes import SessionPair
from lianiq.languages.registry import LanguageId
from lianiq.languages.session import SessionController
from lianiq.pipeline import PipelineRunner
from lianiq.ui import strings
from lianiq.ui.shell.workspaces import WorkspaceId

# CAP-0168 file-size split: the controls, the pair and availability logic and Start/Stop
# moved to these bases. Device enumeration and the capture and runner construction stay
# here, so the names tests and scripts patch on this module are still looked up here.
from lianiq.ui.workspaces.conversation_availability import ConversationAvailability
from lianiq.ui.workspaces.conversation_flow import ConversationFlow
from lianiq.ui.workspaces.conversation_layout import ConversationLayout
from lianiq.ui.workspaces.conversation_notices import ConversationNotices
from lianiq.ui.workspaces.pair_selection import PairSelection

if TYPE_CHECKING:
    from lianiq.ui.main_window import MainWindow


class ConversationWorkspace(
    ConversationLayout, ConversationAvailability, ConversationFlow, QObject
):
    # *Voice output* changed its checked, enabled or tooltip state (Settings mirrors it).
    voice_output_changed = Signal()

    def __init__(self, host: MainWindow) -> None:
        super().__init__(host)
        self.host = host
        self.config = host.config
        self.pipeline = host.pipeline
        bridge = host.bridge
        bridge.result.connect(self._show_result)
        bridge.held.connect(self._show_held)
        bridge.held_resolved.connect(self._held_resolved)
        bridge.busy.connect(self._show_busy)
        bridge.level.connect(self._show_level)
        bridge.session_ready.connect(self._session_ready)
        self.notices = ConversationNotices(self)
        bridge.pipeline_event.connect(self.notices.pipeline_event)
        # Completed turns, in memory only; exported as transcript v2 by capture time.
        self.history: list[TranslationResult] = []
        self.devices: list[AudioDevice] = []
        # Models are constructed and warmed on Start, for the started mode only.
        self.starting = False
        self._pending_session: SessionPair | None = None
        self.diagnostic_wav: Path | None = None
        self.owner = host.session_owner
        self._generation = 0  # the owner generation of this workspace's latest start
        self.owner.register(WorkspaceId.CONVERSATION, self.stop_listening)
        self.owner.subscribe(self._session_changed)
        self.pairs = PairSelection(
            self.config, self.pipeline.registry, lambda: self.session_controller.catalog
        )

    def load_devices(self) -> bool:
        """Fill the device combos; ``False`` (error reported) if enumeration failed."""
        try:
            self.devices = list_audio_devices()
        except RuntimeError as exc:
            self.host.bridge.error.emit(str(exc))
            return False
        self.input_combo.addItem("Windows default", None)
        self.output_combo.addItem("Windows default", None)
        for device in self.devices:
            if device.inputs:
                self.input_combo.addItem(device.name, device.index)
            if device.outputs:
                self.output_combo.addItem(device.name, device.index)
        self._select_device(self.input_combo, self.config.audio.input_device)
        self._select_device(self.output_combo, self.config.audio.output_device)
        return True

    def start_session_services(self) -> None:
        """Capture, runner and the session gate, after the controls exist."""
        bridge = self.host.bridge
        self.capture = MicrophoneCapture(
            self.config.audio,
            on_utterance=self._submit_audio,
            on_level=bridge.level.emit,
            on_error=bridge.error.emit,
        )
        self.pipeline.on_playback_state = self.capture.set_muted

        # Overflow, dropped turns and playback failure become notices; each event carries
        # the generation of the session it was emitted in.
        def emit_event(event) -> None:
            bridge.pipeline_event.emit(event, self._generation)

        self.pipeline.on_event = emit_event
        self.runner = PipelineRunner(
            self.pipeline,
            on_result=bridge.result.emit,
            on_error=bridge.error.emit,
            on_busy=bridge.busy.emit,
            on_held=bridge.held.emit,
            on_event=emit_event,
        )
        # The session gate checks the mode's models and the enumerated audio devices.
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
        # Voice output is bound at Start: ``prepare`` applied the session's output mode.
        if not ready or session is None:
            self.diagnostic_wav = None
            self.owner.mark_idle(self._generation)
            self.start_button.setEnabled(True)
            self.set_session_controls_enabled(True)
            self.state_label.setText("Model error")
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

    @Slot(object)
    def _show_result(self, result: TranslationResult) -> None:
        name = self.pipeline.registry.display_name
        source, target = name(result.source_language), name(result.target_language)
        self.source_panel.append_line(f"{source}: {result.source_text}\n")
        self.target_panel.append_line(f"{target}: {result.translated_text}\n")
        direction = strings.ROUTING_FIXED.format(source=source, target=target)
        self.latency_label.setText(f"{direction} · Processing: {result.total_seconds:.2f} s")
        self.history.append(result)
        self.notices.record_result(result)

    @Slot(object)
    def _show_held(self, _held: HeldTurn) -> None:
        # Nothing is translated until the user resolves the turn in the held-turn bar.
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
        """Re-recognise the held turn as the chosen language; its result is appended."""
        self.held_turn_bar.set_resolving(True)
        self.runner.resolve(held, LanguageId(language), on_done=self.host.bridge.held_resolved.emit)

    @Slot()
    def _held_resolved(self) -> None:
        self.held_turn_bar.set_resolving(False)
        self._refresh_held_bar()

    @Slot(object)
    def _discard_held(self, held: HeldTurn) -> None:
        """Drop the held turn and its audio: no result, no history, no export line."""
        self.pipeline.discard(held)
        self._refresh_held_bar()

    @Slot(bool)
    def _show_busy(self, busy: bool) -> None:
        self.state_label.setText(
            "Translating …" if busy else ("Listening …" if self.capture.running else "Ready")
        )

    @Slot(float)
    def _show_level(self, level: float) -> None:
        self.level_bar.setValue(round(level * 100))
