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

from PySide6.QtCore import QObject, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSplitter,
    QVBoxLayout,
)

from lianiq.audio.capture import MicrophoneCapture
from lianiq.audio.devices import AudioDevice, list_audio_devices
from lianiq.audio.wav import read_pcm16_mono
from lianiq.conversation.routing import HeldTurn
from lianiq.domain import TranslationResult
from lianiq.hardware import ctranslate2_cuda_available, resolve_compute_device
from lianiq.languages.errors import ModeUnavailableError, PairLockedError
from lianiq.languages.modes import OutputKind, SessionPair
from lianiq.languages.registry import LanguageId, LanguagePair
from lianiq.languages.requirements import DeviceReadiness, ModeAvailability, check
from lianiq.languages.session import SessionController, format_transcript_v2
from lianiq.pipeline import PipelineRunner
from lianiq.ui import strings
from lianiq.ui.held_turn_bar import HeldTurnBar
from lianiq.ui.result_panel import ResultPanel
from lianiq.ui.shell.session_owner import SessionBusy, SessionState
from lianiq.ui.shell.workspaces import WorkspaceId, session_busy_message
from lianiq.ui.workspaces.conversation_notices import ConversationNotices
from lianiq.ui.workspaces.pair_selection import PairSelection, conversation_session

if TYPE_CHECKING:
    from lianiq.ui.main_window import MainWindow


class ConversationWorkspace(QObject):
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

    def build(self, layout: QVBoxLayout) -> None:
        """Add the compact control row, the held-turn bar and the result panels to ``layout``."""
        controls = QGridLayout()
        controls.setHorizontalSpacing(10)
        self.pairs.build(controls)
        self.pair_combo, self.mode_combo = self.pairs.pair_combo, self.pairs.mode_combo

        # Each device combo is named after the caption shown above it.
        controls.addWidget(QLabel("Microphone"), 0, 2)
        self.input_combo = QComboBox()
        self.input_combo.setAccessibleName("Microphone")
        controls.addWidget(self.input_combo, 1, 2)
        controls.addWidget(QLabel("Speakers"), 0, 3)
        self.output_combo = QComboBox()
        self.output_combo.setAccessibleName("Speakers")
        controls.addWidget(self.output_combo, 1, 3)
        # The pair and routing combos keep the width of their longest entry; the device
        # combos share the remaining width and may shorten their text (WI-08 DEV-02).
        for combo in (self.input_combo, self.output_combo):
            combo.setSizeAdjustPolicy(
                QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
            )
            combo.setMinimumContentsLength(10)

        self.tts_checkbox = QCheckBox(strings.VOICE_OUTPUT)
        self.tts_checkbox.setAccessibleName(strings.VOICE_OUTPUT)
        # Checked = the saved preference while spoken output is available (see
        # ``refresh_availability``); the output is bound to the session at Start.
        self.tts_checkbox.setChecked(self.config.voice_output)
        self.tts_checkbox.toggled.connect(self._toggle_tts)
        controls.setColumnStretch(2, 1)
        controls.setColumnStretch(3, 1)
        layout.addLayout(controls)

        action_row = QHBoxLayout()
        self.start_button = QPushButton("▶  Start  (F8)")
        self.start_button.setObjectName("primaryButton")
        self.start_button.clicked.connect(self.start_listening)
        self.swap_button = QPushButton("⇄  Switch direction")
        self.swap_button.clicked.connect(self._swap_direction)
        export_button = QPushButton("Export transcript")
        export_button.clicked.connect(self.notices.export_transcript)
        action_row.addWidget(self.start_button)
        action_row.addWidget(self.swap_button)
        action_row.addSpacing(12)
        action_row.addWidget(self.tts_checkbox)
        action_row.addStretch()
        action_row.addWidget(export_button)
        layout.addLayout(action_row)

        self.held_turn_bar = HeldTurnBar(self.pipeline.registry)
        self.held_turn_bar.translate_requested.connect(self._resolve_held)
        self.held_turn_bar.discard_requested.connect(self._discard_held)
        # While the session runs **Stop** is the next action; after a stop it is **Start**.
        self.held_turn_bar.set_focus_return(self.stop_button, self.start_button)
        layout.addWidget(self.held_turn_bar)

        splitter = QSplitter(Qt.Horizontal)
        self.source_panel = ResultPanel("Original", strings.TRANSCRIPT_EMPTY)
        self.target_panel = ResultPanel("Translation", "The translation appears here …")
        splitter.addWidget(self.source_panel)
        splitter.addWidget(self.target_panel)
        splitter.setSizes([1, 1])
        layout.addWidget(splitter, 1)

        activity_row = QHBoxLayout()
        self.level_bar = QProgressBar()
        self.level_bar.setRange(0, 100)
        self.level_bar.setTextVisible(False)
        self.level_bar.setMaximumWidth(180)
        self.state_label = QLabel("Ready")
        self.latency_label = QLabel("Latency: –")
        activity_row.addWidget(QLabel("Microphone"))
        activity_row.addWidget(self.level_bar)
        activity_row.addWidget(self.state_label)
        activity_row.addStretch()
        activity_row.addWidget(self.latency_label)
        layout.addLayout(activity_row)

    @property
    def stop_button(self) -> QPushButton:
        """**Stop (F9)** of the session strip, which stops the active session."""
        return self.host.session_strip.stop_button

    @property
    def source_text(self):
        return self.source_panel.text

    @property
    def target_text(self):
        return self.target_panel.text

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

    @staticmethod
    def _select_device(combo: QComboBox, index: int | None) -> None:
        found = combo.findData(index)
        combo.setCurrentIndex(max(found, 0))

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

    def connect_selection(self) -> None:
        self.populate_pairs()
        self.pair_combo.currentIndexChanged.connect(self._pair_selected)
        self.mode_combo.currentIndexChanged.connect(self._routing_selected)
        self.refresh_availability()

    def current_fixed_source(self) -> LanguageId | None:
        """The fixed source the routing control selects, or ``None`` for Automatic."""
        return self.pairs.current_fixed_source()

    def current_pair(self) -> LanguagePair | None:
        """The selected language pair; ``None`` if no ready pair can be selected."""
        return self.pairs.current_pair()

    def device_readiness(self) -> DeviceReadiness:
        """Microphone and playback availability from the enumerated audio devices."""
        return DeviceReadiness(
            microphone=any(device.inputs for device in self.devices),
            playback=any(device.outputs for device in self.devices),
        )

    def set_session_controls_enabled(self, enabled: bool) -> None:
        # Pair, routing and output are bound at Start (AC-13, PO decision Q2): changing
        # them needs Stop. While locked, the tooltip says why they are disabled.
        for control in (self.pair_combo, self.mode_combo, self.swap_button, self.tts_checkbox):
            control.setEnabled(enabled)
            control.setToolTip("" if enabled else strings.LOCKED_TOOLTIP)
        if enabled:
            self.refresh_availability()
        else:
            self.voice_output_changed.emit()

    def set_devices_enabled(self, enabled: bool) -> None:
        self.input_combo.setEnabled(enabled)
        self.output_combo.setEnabled(enabled)

    conversation_session = staticmethod(conversation_session)

    def populate_pairs(self) -> None:
        """Ready qualified pairs, then every planned language as a disabled entry (AC-02)."""
        self._show_pair(*self.pairs.populate_pairs())

    def _populate_routing(self, pair: LanguagePair | None, fixed_source: LanguageId | None) -> None:
        self._show_pair(*self.pairs.populate_routing(pair, fixed_source))

    def _show_pair(self, title: str, placeholder: str) -> None:
        self.host.setWindowTitle(title)
        self.source_text.setPlaceholderText(placeholder)

    def refresh_availability(self) -> None:
        """Drive the routing entries, *Voice output* and **Start** from ``check()``."""
        if self.host.session_locked():
            return
        try:
            self._refresh_availability()
        finally:
            self.voice_output_changed.emit()

    def _refresh_availability(self) -> None:
        status = self.host.statusBar()
        pair = self.current_pair()
        for control in (self.mode_combo, self.swap_button):
            control.setEnabled(pair is not None)
        if pair is None:
            self.start_button.setEnabled(False)
            self.tts_checkbox.setEnabled(False)
            self.state_label.setText("Not available")
            status.showMessage(strings.NO_PAIR_READY)
            return
        catalog = self.session_controller.catalog
        devices = self.device_readiness()
        model = self.mode_combo.model()
        for index in range(self.mode_combo.count()):
            data = self.mode_combo.itemData(index)
            entry = self.conversation_session(
                pair, LanguageId(data) if data else None, OutputKind.TEXT
            )
            availability = check(entry, catalog, devices)
            item = model.item(index)
            item.setEnabled(availability.available)
            item.setToolTip(
                "" if availability.available else self.host.describe_missing(availability)
            )
        fixed_source = self.current_fixed_source()
        text = check(
            self.conversation_session(pair, fixed_source, OutputKind.TEXT), catalog, devices
        )
        spoken = check(
            self.conversation_session(pair, fixed_source, OutputKind.SPOKEN), catalog, devices
        )
        # Voice readiness never makes text output unavailable (IS §7).
        voice_missing = tuple(item for item in spoken.missing if item not in text.missing)
        voice_text = (
            self.host.describe_missing(ModeAvailability(False, voice_missing))
            if voice_missing
            else ""
        )
        self.tts_checkbox.setEnabled(not voice_missing)
        self.tts_checkbox.setToolTip(voice_text)
        self.notices.voice(voice_text)
        self.tts_checkbox.blockSignals(True)
        self.tts_checkbox.setChecked(self.config.voice_output and not voice_missing)
        self.tts_checkbox.blockSignals(False)
        availability = self.session_controller.availability(self.session_pair())
        self.start_button.setEnabled(availability.available)
        self.notices.availability(availability.available)
        if availability.available:
            if self.state_label.text() == "Not available":
                self.state_label.setText("Ready")
            status.showMessage("Models load on Start, only for the selected mode.")
        else:
            self.state_label.setText("Not available")
            status.showMessage(self.host.describe_missing(availability))

    @Slot(int)
    def _pair_selected(self, _index: int) -> None:
        pair = self.current_pair()
        if pair is None or self.host.session_locked():
            return
        languages = self.config.languages
        fixed_source = self.current_fixed_source()
        if fixed_source not in pair:
            fixed_source = None
        languages.pair = list(pair.members)
        languages.routing = "bidirectional" if fixed_source is None else "fixed"
        languages.fixed_source = fixed_source
        # The Call Bridge lanes and labels follow the pair and ``call_bridge.local_language``.
        self.host.call_bridge.update_languages()
        self._populate_routing(pair, fixed_source)
        self._selection_changed()

    @Slot(int)
    def _routing_selected(self, _index: int) -> None:
        if not self.host.session_locked():
            self._selection_changed()

    def _selection_changed(self) -> None:
        """A stopped selection change selects the next session (``SessionController.change``)."""
        try:
            self.session_controller.change(self.session_pair())
        except PairLockedError:
            self.notices.pair_locked()
            return
        self.refresh_availability()

    def recognition_device(self) -> str:
        """The compute device speech recognition runs (or will run) on."""
        return self._recognition_device()

    def translation_device(self) -> str:
        """The compute device translation runs (or will run) on."""
        device = getattr(self.pipeline.translator, "device", None)
        if device is None:
            device = resolve_compute_device(
                self.config.translation.device, ctranslate2_cuda_available()
            )
        return device

    def _recognition_device(self) -> str:
        device = getattr(self.pipeline.recognizer, "device", None)
        if device is None:
            # The recogniser is built on Start; report the device it will use.
            device = resolve_compute_device(
                self.config.speech_to_text.device, ctranslate2_cuda_available()
            )
        return device

    def session_pair(self) -> SessionPair:
        """The conversation session the current controls select (microphone input)."""
        pair = self.current_pair()
        if pair is None:
            raise RuntimeError(strings.NO_PAIR_READY)
        output = OutputKind.SPOKEN if self.tts_checkbox.isChecked() else OutputKind.TEXT
        return self.conversation_session(pair, self.current_fixed_source(), output)

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
            self.config.audio.input_device = self.input_combo.currentData()
            self.config.audio.output_device = self.output_combo.currentData()
            self.pipeline.output_device = self.config.audio.output_device
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

    def _session_changed(self, state: SessionState, active: WorkspaceId | None) -> None:
        """While another mode holds the session, **Start** says why it is disabled."""
        busy = state is not SessionState.IDLE and active is not WorkspaceId.CONVERSATION
        if busy and active is not None:
            self.start_button.setEnabled(False)
            self.start_button.setToolTip(session_busy_message(active))
        else:
            self.start_button.setToolTip("")

    @Slot(bool)
    def _toggle_tts(self, enabled: bool) -> None:
        # The saved preference; a running session keeps the output it was started with.
        self.config.voice_output = enabled
        self.refresh_availability()

    @Slot()
    def _swap_direction(self) -> None:
        """Fixed source to the other member; Automatic to the first available direction."""
        pair = self.current_pair()
        if pair is None or self.host.session_locked():
            return
        current = self.current_fixed_source()
        candidates = pair.members if current is None else (pair.other(current),)
        model = self.mode_combo.model()
        for source in candidates:
            index = self.mode_combo.findData(source)
            if model.item(index).isEnabled():
                self.mode_combo.setCurrentIndex(index)
                self.notices.direction(None)
                return
        # Spec §2.3.4 "mode unavailable": an info notice; the direction stays unchanged.
        self.notices.direction(model.item(self.mode_combo.findData(candidates[0])).toolTip())

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
