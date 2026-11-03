from __future__ import annotations

import datetime as dt
import itertools
import sys
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QCloseEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from lianiq.audio.capture import MicrophoneCapture
from lianiq.audio.capture_stream import EndpointCaptureStream
from lianiq.audio.devices import AudioDevice, list_audio_devices
from lianiq.audio.endpoints import list_audio_endpoints
from lianiq.audio.playback_stream import EndpointPlaybackStream
from lianiq.audio.wav import read_pcm16_mono
from lianiq.call_bridge.contracts import (
    BridgeEvent,
    BridgeEventKind,
    BridgeState,
    EndpointRole,
    LaneId,
)
from lianiq.call_bridge.controller import FullDuplexBridgeController
from lianiq.call_bridge.inference_scheduler import InferenceScheduler
from lianiq.call_bridge.translation_lane import TranslationLane
from lianiq.config import AppConfig
from lianiq.conversation.routing import HeldTurn
from lianiq.domain import TranslationResult
from lianiq.hardware import ctranslate2_cuda_available, resolve_compute_device
from lianiq.languages.errors import LanguageContractError, ModeUnavailableError, PairLockedError
from lianiq.languages.modes import (
    CALL_BRIDGE_MODE,
    InputKind,
    OutputKind,
    RoutingKind,
    SessionPair,
    UsageMode,
)
from lianiq.languages.registry import Availability, LanguageId, LanguagePair
from lianiq.languages.requirements import DeviceReadiness, ModeAvailability, check, describe
from lianiq.languages.session import SessionController, format_transcript_v2
from lianiq.pipeline import PipelineRunner, TranslationPipeline
from lianiq.ui import strings
from lianiq.ui.call_bridge_panel import CallBridgePanel
from lianiq.ui.held_turn_bar import HeldTurnBar

# ``mode_combo`` item data: a fixed source language ID, or this value for Automatic.
AUTOMATIC_ROUTING = ""
ROUTING_CONTROL_LABEL = "Conversation direction"
# A pair is ready when one of its main-window routings has every model it needs.
MODELS_ONLY = DeviceReadiness(microphone=True, playback=True)
# Call Bridge lanes stay German (local) / Mandarin (remote) until CAP-0169 WI-05 derives
# them from the pair and ``call_bridge.local_language``.
CALL_BRIDGE_LOCAL = LanguageId("de")
CALL_BRIDGE_REMOTE = LanguageId("zh-Hans")
ROUTE_TEST_TEXT = {CALL_BRIDGE_LOCAL: "Kopfhörer-Test.", CALL_BRIDGE_REMOTE: "通话麦克风测试。"}


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


class MainWindow(QMainWindow):
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
        self.bridge.result.connect(self._show_result)
        self.bridge.held.connect(self._show_held)
        self.bridge.held_resolved.connect(self._held_resolved)
        self.bridge.error.connect(self._show_error)
        self.bridge.busy.connect(self._show_busy)
        self.bridge.level.connect(self._show_level)
        self.bridge.session_ready.connect(self._session_ready)
        self.bridge.call_bridge_ready.connect(self._call_bridge_ready)
        self.bridge.call_bridge_event.connect(self._show_call_bridge_event)
        self.bridge.call_bridge_level.connect(self._show_call_bridge_level)
        self.bridge.call_bridge_capture_fault.connect(self._handle_call_bridge_capture_fault)
        # Completed turns, in memory only; exported as transcript v2 by capture time.
        self.history: list[TranslationResult] = []
        self.devices: list[AudioDevice] = []
        self.call_bridge_controller: FullDuplexBridgeController | None = None
        # Models are constructed and warmed on Start, for the started mode only.
        self._starting = False
        self._call_bridge_starting = False
        # Each Start gets a generation; a ready signal of a cancelled Start is ignored.
        self._start_generation = 0
        self._pending_assignments = None
        self._pending_session: SessionPair | None = None
        self._diagnostic_wav: Path | None = None
        self._ready_pairs: list[LanguagePair] = []
        self._endpoint_monitor = QTimer(self)
        self._endpoint_monitor.setInterval(2_000)
        self._endpoint_monitor.timeout.connect(self._reconcile_call_bridge_endpoints)

        self.setWindowTitle("lianiq")
        self.resize(1120, 720)
        self.setMinimumSize(850, 560)
        self._build_ui()
        self._load_devices()
        self._apply_style()

        self.capture = MicrophoneCapture(
            config.audio,
            on_utterance=self._submit_audio,
            on_level=self.bridge.level.emit,
            on_error=self.bridge.error.emit,
        )
        self.pipeline.on_playback_state = self.capture.set_muted
        self.runner = PipelineRunner(
            pipeline,
            on_result=self.bridge.result.emit,
            on_error=self.bridge.error.emit,
            on_busy=self.bridge.busy.emit,
            on_held=self.bridge.held.emit,
        )
        # The session gate checks the mode's models and the enumerated audio devices.
        self.session_controller = SessionController(
            pipeline,
            self.runner,
            devices=self.device_readiness,
            capture=self.capture,
        )
        self.call_bridge_panel.set_models_ready(True)
        self._populate_pairs()
        self.pair_combo.currentIndexChanged.connect(self._pair_selected)
        self.mode_combo.currentIndexChanged.connect(self._routing_selected)
        self._refresh_availability()
        if "--diagnostic-wav" in sys.argv:
            argument_index = sys.argv.index("--diagnostic-wav") + 1
            if argument_index >= len(sys.argv):
                QTimer.singleShot(
                    0, lambda: self._show_error("--diagnostic-wav requires a WAV file path")
                )
            else:
                self._diagnostic_wav = Path(sys.argv[argument_index])
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

        controls = QGridLayout()
        controls.setHorizontalSpacing(10)
        pair_label = QLabel(strings.PAIR_LABEL)
        controls.addWidget(pair_label, 0, 0)
        self.pair_combo = QComboBox()
        self.pair_combo.setAccessibleName(strings.PAIR_LABEL)
        pair_label.setBuddy(self.pair_combo)
        controls.addWidget(self.pair_combo, 1, 0)
        routing_label = QLabel(ROUTING_CONTROL_LABEL)
        controls.addWidget(routing_label, 0, 1)
        self.mode_combo = QComboBox()
        self.mode_combo.setAccessibleName(ROUTING_CONTROL_LABEL)
        routing_label.setBuddy(self.mode_combo)
        controls.addWidget(self.mode_combo, 1, 1)

        controls.addWidget(QLabel("Microphone"), 0, 2)
        self.input_combo = QComboBox()
        controls.addWidget(self.input_combo, 1, 2)
        controls.addWidget(QLabel("Speakers"), 0, 3)
        self.output_combo = QComboBox()
        controls.addWidget(self.output_combo, 1, 3)

        controls.addWidget(QLabel("Model profile"), 0, 4)
        self.model_combo = QComboBox()
        self.model_combo.addItem("Balanced · Whisper small + MarianMT", "balanced")
        self.model_combo.setToolTip("The installed profile is optimized for this EliteBook.")
        controls.addWidget(self.model_combo, 1, 4)

        self.tts_checkbox = QCheckBox("Voice output")
        self.tts_checkbox.setAccessibleName("Voice output")
        # Checked = the saved preference while spoken output is available (see
        # ``_refresh_availability``); the output is bound to the session at Start.
        self.tts_checkbox.setChecked(self.config.voice_output)
        self.tts_checkbox.toggled.connect(self._toggle_tts)
        controls.addWidget(self.tts_checkbox, 1, 5)
        self.gpu_checkbox = QCheckBox("CUDA GPU")
        recognition_device = self._recognition_device()
        self.gpu_checkbox.setChecked(recognition_device == "cuda")
        self.gpu_checkbox.setEnabled(False)
        runtime_device = recognition_device.upper()
        self.gpu_checkbox.setToolTip(f"Active inference device: {runtime_device}")
        controls.addWidget(self.gpu_checkbox, 1, 6)
        controls.setColumnStretch(2, 2)
        controls.setColumnStretch(3, 2)
        layout.addLayout(controls)

        action_row = QHBoxLayout()
        self.start_button = QPushButton("▶  Start  (F8)")
        self.start_button.setObjectName("primaryButton")
        self.start_button.clicked.connect(self.start_listening)
        self.stop_button = QPushButton("■  Stop  (F9)")
        self.stop_button.clicked.connect(self.stop_listening)
        self.stop_button.setEnabled(False)
        self.swap_button = QPushButton("⇄  Switch direction")
        self.swap_button.clicked.connect(self._swap_direction)
        export_button = QPushButton("Export transcript")
        export_button.clicked.connect(self._export_history)
        action_row.addWidget(self.start_button)
        action_row.addWidget(self.stop_button)
        action_row.addWidget(self.swap_button)
        action_row.addStretch()
        action_row.addWidget(export_button)
        layout.addLayout(action_row)

        self.call_bridge_panel = CallBridgePanel(self.config.call_bridge)
        self.call_bridge_panel.start_requested.connect(self.start_call_bridge)
        self.call_bridge_panel.stop_requested.connect(self.stop_call_bridge)
        self.call_bridge_panel.route_test_requested.connect(self._run_call_bridge_route_test)
        layout.addWidget(self.call_bridge_panel)

        self.held_turn_bar = HeldTurnBar(self.pipeline.registry)
        self.held_turn_bar.translate_requested.connect(self._resolve_held)
        self.held_turn_bar.discard_requested.connect(self._discard_held)
        layout.addWidget(self.held_turn_bar)

        splitter = QSplitter(Qt.Horizontal)
        source_panel, self.source_text = self._text_panel("Original", "Speak …")
        target_panel, self.target_text = self._text_panel(
            "Translation", "The translation appears here …"
        )
        splitter.addWidget(source_panel)
        splitter.addWidget(target_panel)
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

        self.setCentralWidget(root)
        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("Models load when the first speech segment is processed.")

    @staticmethod
    def _text_panel(title: str, placeholder: str) -> tuple[QWidget, QPlainTextEdit]:
        panel = QWidget()
        panel.setObjectName("textPanel")
        layout = QVBoxLayout(panel)
        heading = QLabel(title)
        heading.setObjectName("panelTitle")
        text = QPlainTextEdit()
        text.setReadOnly(True)
        text.setPlaceholderText(placeholder)
        text.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(heading)
        layout.addWidget(text)
        return panel, text

    def _load_devices(self) -> None:
        try:
            self.devices = list_audio_devices()
        except RuntimeError as exc:
            self.bridge.error.emit(str(exc))
            return
        self.input_combo.addItem("Windows default", None)
        self.output_combo.addItem("Windows default", None)
        for device in self.devices:
            if device.inputs:
                self.input_combo.addItem(device.name, device.index)
            if device.outputs:
                self.output_combo.addItem(device.name, device.index)
        self._select_device(self.input_combo, self.config.audio.input_device)
        self._select_device(self.output_combo, self.config.audio.output_device)
        try:
            inventory = list_audio_endpoints()
        except (RuntimeError, ValueError) as exc:
            self.call_bridge_panel.set_endpoints([])
            self.call_bridge_panel.set_state("unavailable", str(exc))
        else:
            self.call_bridge_panel.set_endpoints(inventory.endpoints)

    @staticmethod
    def _select_device(combo: QComboBox, index: int | None) -> None:
        found = combo.findData(index)
        combo.setCurrentIndex(max(found, 0))

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

    def current_fixed_source(self) -> LanguageId | None:
        """The fixed source the routing control selects, or ``None`` for Automatic."""
        data = self.mode_combo.currentData()
        return LanguageId(data) if data else None

    def current_pair(self) -> LanguagePair | None:
        """The selected language pair; ``None`` if no ready pair can be selected."""
        data = self.pair_combo.currentData()
        return data if isinstance(data, LanguagePair) else None

    def device_readiness(self) -> DeviceReadiness:
        """Microphone and playback availability from the enumerated audio devices."""
        return DeviceReadiness(
            microphone=any(device.inputs for device in self.devices),
            playback=any(device.outputs for device in self.devices),
        )

    def _select_fixed_source(self, source: LanguageId | None) -> None:
        found = self.mode_combo.findData(source or AUTOMATIC_ROUTING)
        self.mode_combo.setCurrentIndex(max(found, 0))

    def _session_locked(self) -> bool:
        return (
            self._starting
            or self.capture.running
            or self._call_bridge_starting
            or self.call_bridge_controller is not None
        )

    def _set_session_controls_enabled(self, enabled: bool) -> None:
        # Pair, routing and output are bound at Start (AC-13, PO decision Q2): changing
        # them needs Stop. While locked, the tooltip says why they are disabled.
        for control in (self.pair_combo, self.mode_combo, self.swap_button, self.tts_checkbox):
            control.setEnabled(enabled)
            control.setToolTip("" if enabled else strings.LOCKED_TOOLTIP)
        if enabled:
            self._refresh_availability()

    @staticmethod
    def _conversation_session(
        pair: LanguagePair, fixed_source: LanguageId | None, output: OutputKind
    ) -> SessionPair:
        routing = RoutingKind.BIDIRECTIONAL if fixed_source is None else RoutingKind.FIXED
        return SessionPair(
            pair, UsageMode(InputKind.MICROPHONE, routing, output), fixed_source=fixed_source
        )

    def _describe_missing(self, availability: ModeAvailability) -> str:
        items = ", ".join(describe(item, self.pipeline.registry) for item in availability.missing)
        return strings.MODE_UNAVAILABLE.format(items=items)

    def _pair_name(self, pair: LanguagePair) -> str:
        name = self.pipeline.registry.display_name
        return strings.PAIR_NAME.format(a=name(pair.first), b=name(pair.second))

    def _pair_ready(self, pair: LanguagePair) -> bool:
        catalog = self.session_controller.catalog
        return any(
            check(
                self._conversation_session(pair, source, OutputKind.TEXT), catalog, MODELS_ONLY
            ).available
            for source in (None, *pair.members)
        )

    def _populate_pairs(self) -> None:
        """Ready qualified pairs, then every planned language as a disabled entry (AC-02)."""
        registry = self.pipeline.registry
        qualified = [
            item.id for item in registry.languages() if item.availability is Availability.QUALIFIED
        ]
        pairs = [registry.pair(a, b) for a, b in itertools.combinations(qualified, 2)]
        self._ready_pairs = [pair for pair in pairs if self._pair_ready(pair)]
        self.pair_combo.blockSignals(True)
        self.pair_combo.clear()
        for pair in self._ready_pairs:
            self.pair_combo.addItem(self._pair_name(pair), pair)
        if not self._ready_pairs:
            self._add_disabled_item(self.pair_combo, strings.PAIR_NONE_READY)
        for item in registry.languages():
            if item.availability is Availability.PLANNED:
                self._add_disabled_item(
                    self.pair_combo, f"{item.english_name} {strings.PAIR_PLANNED_SUFFIX}"
                )
        try:
            configured = registry.pair(*self.config.languages.pair)
        except LanguageContractError:
            configured = None  # an unusable saved pair falls back to the first ready one
        index = self._ready_pairs.index(configured) if configured in self._ready_pairs else 0
        self.pair_combo.setCurrentIndex(index)
        self.pair_combo.blockSignals(False)
        languages = self.config.languages
        selected = self.current_pair()
        if selected is not None and selected != configured:
            languages.pair = list(selected.members)
            languages.routing, languages.fixed_source = "bidirectional", None
        fixed = LanguageId(languages.fixed_source) if languages.routing == "fixed" else None
        self._populate_routing(selected, fixed)

    @staticmethod
    def _add_disabled_item(combo: QComboBox, text: str) -> None:
        """A visible entry that cannot be selected; its state is part of its text."""
        combo.addItem(text, None)
        item = combo.model().item(combo.count() - 1)
        item.setEnabled(False)
        item.setSelectable(False)
        item.setToolTip(text)

    def _populate_routing(self, pair: LanguagePair | None, fixed_source: LanguageId | None) -> None:
        """Automatic and both fixed directions of ``pair``, labelled with registry names."""
        name = self.pipeline.registry.display_name
        self.mode_combo.blockSignals(True)
        self.mode_combo.clear()
        title, placeholder = "lianiq", "Speak …"
        if pair is not None:
            self.mode_combo.addItem(
                strings.ROUTING_AUTOMATIC.format(a=name(pair.first), b=name(pair.second)),
                AUTOMATIC_ROUTING,
            )
            for source in pair.members:
                label = strings.ROUTING_FIXED.format(
                    source=name(source), target=name(pair.other(source))
                )
                self.mode_combo.addItem(label, source)
            self._select_fixed_source(fixed_source if fixed_source in pair else None)
            title = strings.WINDOW_TITLE.format(pair=self._pair_name(pair))
            placeholder = f"Speak in {name(pair.first)} or {name(pair.second)} …"
        self.mode_combo.blockSignals(False)
        self.setWindowTitle(title)
        self.source_text.setPlaceholderText(placeholder)

    def _refresh_availability(self) -> None:
        """Drive the routing entries, *Voice output* and **Start** from ``check()``."""
        if self._session_locked():
            return
        pair = self.current_pair()
        for control in (self.mode_combo, self.swap_button):
            control.setEnabled(pair is not None)
        if pair is None:
            self.start_button.setEnabled(False)
            self.tts_checkbox.setEnabled(False)
            self.state_label.setText("Not available")
            self.statusBar().showMessage(strings.NO_PAIR_READY)
            return
        catalog = self.session_controller.catalog
        devices = self.device_readiness()
        model = self.mode_combo.model()
        for index in range(self.mode_combo.count()):
            data = self.mode_combo.itemData(index)
            entry = self._conversation_session(
                pair, LanguageId(data) if data else None, OutputKind.TEXT
            )
            availability = check(entry, catalog, devices)
            item = model.item(index)
            item.setEnabled(availability.available)
            item.setToolTip("" if availability.available else self._describe_missing(availability))
        fixed_source = self.current_fixed_source()
        text = check(
            self._conversation_session(pair, fixed_source, OutputKind.TEXT), catalog, devices
        )
        spoken = check(
            self._conversation_session(pair, fixed_source, OutputKind.SPOKEN), catalog, devices
        )
        # Voice readiness never makes text output unavailable (IS §7).
        voice_missing = tuple(item for item in spoken.missing if item not in text.missing)
        self.tts_checkbox.setEnabled(not voice_missing)
        self.tts_checkbox.setToolTip(
            self._describe_missing(ModeAvailability(False, voice_missing)) if voice_missing else ""
        )
        self.tts_checkbox.blockSignals(True)
        self.tts_checkbox.setChecked(self.config.voice_output and not voice_missing)
        self.tts_checkbox.blockSignals(False)
        availability = self.session_controller.availability(self.session_pair())
        self.start_button.setEnabled(availability.available)
        if availability.available:
            if self.state_label.text() == "Not available":
                self.state_label.setText("Ready")
            self.statusBar().showMessage("Models load on Start, only for the selected mode.")
        else:
            self.state_label.setText("Not available")
            self.statusBar().showMessage(self._describe_missing(availability))

    @Slot(int)
    def _pair_selected(self, _index: int) -> None:
        pair = self.current_pair()
        if pair is None or self._session_locked():
            return
        languages = self.config.languages
        fixed_source = self.current_fixed_source()
        if fixed_source not in pair:
            fixed_source = None
        languages.pair = list(pair.members)
        languages.routing = "bidirectional" if fixed_source is None else "fixed"
        languages.fixed_source = fixed_source
        self._populate_routing(pair, fixed_source)
        self._selection_changed()

    @Slot(int)
    def _routing_selected(self, _index: int) -> None:
        if not self._session_locked():
            self._selection_changed()

    def _selection_changed(self) -> None:
        """A stopped selection change selects the next session (``SessionController.change``)."""
        try:
            self.session_controller.change(self.session_pair())
        except PairLockedError:
            self.statusBar().showMessage(strings.LOCKED_TOOLTIP, 10_000)
            return
        self._refresh_availability()

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
        return self._conversation_session(pair, self.current_fixed_source(), output)

    def call_bridge_session(self) -> SessionPair:
        registry = self.pipeline.registry
        return SessionPair(
            registry.pair(*self.config.languages.pair),
            CALL_BRIDGE_MODE,
            local_language=registry.get(self.config.call_bridge.local_language).id,
        )

    def _prepare_in_background(self, session: SessionPair, ready: Signal) -> None:
        self._start_generation += 1
        generation = self._start_generation

        def prepare() -> None:
            try:
                self.pipeline.prepare(session)
            except Exception as exc:  # noqa: BLE001 - background boundary reports model failures.
                ready.emit(generation, False, str(exc))
            else:
                ready.emit(generation, True, "")

        threading.Thread(target=prepare, name="model-warmup", daemon=True).start()

    @Slot(int, bool, str)
    def _session_ready(self, generation: int, ready: bool, message: str) -> None:
        if not self._starting or generation != self._start_generation:
            return  # This Start was stopped or superseded while its models were loading.
        self._starting = False
        session, self._pending_session = self._pending_session, None
        # Voice output is bound at Start: ``prepare`` applied the session's output mode.
        if not ready or session is None:
            self._diagnostic_wav = None
            self.start_button.setEnabled(True)
            self._set_session_controls_enabled(True)
            self.state_label.setText("Model error")
            self.statusBar().showMessage(message)
            return
        self._begin_listening(session)
        path, self._diagnostic_wav = self._diagnostic_wav, None
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
            self.bridge.error.emit(f"Diagnostic WAV failed: {exc}")

    @Slot()
    def start_listening(self) -> None:
        if self.call_bridge_controller is not None or self._call_bridge_starting:
            self._show_error("Stop call bridge mode before starting conversation capture")
            return
        if self._starting or self.capture.running:
            return
        try:
            session = self.session_pair()
            availability = self.session_controller.availability(session)
        except Exception as exc:  # noqa: BLE001 - GUI boundary reports invalid selections.
            self._show_error(str(exc))
            return
        if not availability.available:
            self._diagnostic_wav = None
            self._show_unavailable(availability.missing)
            return
        self._starting = True
        self._pending_session = session
        self._set_session_controls_enabled(False)
        self.start_button.setEnabled(False)
        self.state_label.setText("Loading models …")
        self.statusBar().showMessage("Loading the models the selected mode requires …")
        self._prepare_in_background(session, self.bridge.session_ready)

    def _show_unavailable(self, missing) -> None:
        self._show_error(self._describe_missing(ModeAvailability(False, tuple(missing))))

    def _begin_listening(self, session: SessionPair) -> None:
        try:
            self.config.audio.input_device = self.input_combo.currentData()
            self.config.audio.output_device = self.output_combo.currentData()
            self.pipeline.output_device = self.config.audio.output_device
            self.session_controller.start(session)
        except ModeUnavailableError as exc:
            self.start_button.setEnabled(True)
            self._set_session_controls_enabled(True)
            self._show_unavailable(exc.missing)
            return
        except Exception as exc:  # noqa: BLE001 - GUI boundary reports dependency/device failures.
            self.start_button.setEnabled(True)
            self._set_session_controls_enabled(True)
            self._show_error(str(exc))
            return
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.input_combo.setEnabled(False)
        self.output_combo.setEnabled(False)
        self.state_label.setText("Listening …")
        self.statusBar().showMessage("Offline capture is active")

    @Slot()
    def stop_listening(self) -> None:
        self._starting = False
        self._pending_session = None
        self._diagnostic_wav = None
        # Queued turns finish with their bound pair; unresolved held turns are discarded.
        report = self.session_controller.stop()
        self.held_turn_bar.clear()
        self.start_button.setEnabled(not self._call_bridge_starting)
        self.stop_button.setEnabled(False)
        self.input_combo.setEnabled(True)
        self.output_combo.setEnabled(True)
        self._set_session_controls_enabled(self.call_bridge_controller is None)
        self.level_bar.setValue(0)
        self.state_label.setText("Ready")
        message = "Capture stopped"
        if report.discarded:
            message += f"; {len(report.discarded)} turn(s) with an unclear language were discarded"
        self.statusBar().showMessage(message)

    @Slot()
    def start_call_bridge(self) -> None:
        if self.call_bridge_controller is not None or self._call_bridge_starting:
            return
        if self.capture.running or self._starting:
            self.stop_listening()
        try:
            assignments = self.call_bridge_panel.assignments()
            session = self.call_bridge_session()
        except Exception as exc:  # noqa: BLE001 - GUI boundary reports setup failures.
            self._show_error(str(exc))
            return
        self._call_bridge_starting = True
        self._pending_assignments = assignments
        self.call_bridge_panel.set_models_ready(False)
        self.start_button.setEnabled(False)
        self.statusBar().showMessage("Loading the call bridge models …")
        self._prepare_in_background(session, self.bridge.call_bridge_ready)

    @Slot(int, bool, str)
    def _call_bridge_ready(self, generation: int, ready: bool, message: str) -> None:
        if not self._call_bridge_starting or generation != self._start_generation:
            return
        self._call_bridge_starting = False
        assignments, self._pending_assignments = self._pending_assignments, None
        self.call_bridge_panel.set_models_ready(True)
        if not ready or assignments is None:
            self.start_button.setEnabled(True)
            self._show_error(message or "Call bridge setup was cancelled")
            return
        self._begin_call_bridge(assignments)

    def _begin_call_bridge(self, assignments) -> None:
        try:
            recognizer = self.pipeline.speech_recognizer()
            translator = self.pipeline.text_translator()
            synthesizer = self.pipeline.voice_synthesizer()
            validate_voice_files = getattr(synthesizer, "validate_voice_files", None)
            if validate_voice_files is not None:
                validate_voice_files([CALL_BRIDGE_LOCAL, CALL_BRIDGE_REMOTE])
            scheduler = InferenceScheduler(max_concurrent=2)
            outbound_playback = EndpointPlaybackStream(
                assignments[EndpointRole.CALL_MICROPHONE_RENDER]
            )
            inbound_playback = EndpointPlaybackStream(assignments[EndpointRole.LOCAL_HEADPHONES])
            outbound_lane = TranslationLane(
                LaneId.OUTBOUND,
                CALL_BRIDGE_LOCAL,
                CALL_BRIDGE_REMOTE,
                recognizer,
                translator,
                synthesizer,
                outbound_playback.play,
                scheduler,
                max_pending_age_ms=self.config.call_bridge.max_pending_age_ms,
                on_result=self.bridge.result.emit,
                on_event=self.bridge.call_bridge_event.emit,
            )
            inbound_lane = TranslationLane(
                LaneId.INBOUND,
                CALL_BRIDGE_REMOTE,
                CALL_BRIDGE_LOCAL,
                recognizer,
                translator,
                synthesizer,
                inbound_playback.play,
                scheduler,
                max_pending_age_ms=self.config.call_bridge.max_pending_age_ms,
                on_result=self.bridge.result.emit,
                on_event=self.bridge.call_bridge_event.emit,
            )
            outbound_capture = EndpointCaptureStream(
                assignments[EndpointRole.LOCAL_MICROPHONE],
                self.config.audio,
                outbound_lane.submit,
                on_level=lambda level: self.bridge.call_bridge_level.emit(
                    EndpointRole.LOCAL_MICROPHONE, level
                ),
                on_error=lambda message: self.bridge.call_bridge_capture_fault.emit(
                    EndpointRole.LOCAL_MICROPHONE, message
                ),
            )
            inbound_capture = EndpointCaptureStream(
                assignments[EndpointRole.CALL_SPEAKER_CAPTURE],
                self.config.audio,
                inbound_lane.submit,
                on_level=lambda level: self.bridge.call_bridge_level.emit(
                    EndpointRole.CALL_SPEAKER_CAPTURE, level
                ),
                on_error=lambda message: self.bridge.call_bridge_capture_fault.emit(
                    EndpointRole.CALL_SPEAKER_CAPTURE, message
                ),
            )
            controller = FullDuplexBridgeController(
                assignments,
                outbound_lane,
                inbound_lane,
                outbound_capture,
                inbound_capture,
                on_event=self.bridge.call_bridge_event.emit,
                endpoint_ports={
                    EndpointRole.LOCAL_MICROPHONE: outbound_capture,
                    EndpointRole.CALL_MICROPHONE_RENDER: outbound_playback,
                    EndpointRole.CALL_SPEAKER_CAPTURE: inbound_capture,
                    EndpointRole.LOCAL_HEADPHONES: inbound_playback,
                },
            )
            self.call_bridge_controller = controller
            controller.start()
        except Exception as exc:  # noqa: BLE001 - GUI boundary reports setup failures.
            self.call_bridge_controller = None
            self.start_button.setEnabled(True)
            self._show_error(str(exc))
            return
        self.call_bridge_panel.apply_to_config()
        self.call_bridge_panel.set_running(True)
        self._endpoint_monitor.start()
        self.start_button.setEnabled(False)
        self._set_session_controls_enabled(False)
        self.input_combo.setEnabled(False)
        self.output_combo.setEnabled(False)
        self.statusBar().showMessage("Fail-closed full-duplex call bridge is active")

    @Slot()
    def stop_call_bridge(self) -> None:
        self._endpoint_monitor.stop()
        controller, self.call_bridge_controller = self.call_bridge_controller, None
        if controller is not None and not controller.stop(timeout=10.0):
            self._show_error("Call bridge workers did not stop within the shutdown contract")
        self._call_bridge_starting = False
        self._pending_assignments = None
        self.call_bridge_panel.set_running(False)
        self.call_bridge_panel.set_models_ready(True)
        self.start_button.setEnabled(not self._starting and not self.capture.running)
        self._set_session_controls_enabled(not self._starting and not self.capture.running)
        self.input_combo.setEnabled(True)
        self.output_combo.setEnabled(True)
        for role in (EndpointRole.LOCAL_MICROPHONE, EndpointRole.CALL_SPEAKER_CAPTURE):
            self.call_bridge_panel.set_level(role, 0.0)
        self.statusBar().showMessage("Call bridge stopped; all explicit endpoints were released")

    @Slot()
    def _reconcile_call_bridge_endpoints(self) -> None:
        if self.call_bridge_controller is None:
            return
        try:
            inventory = list_audio_endpoints()
            self.call_bridge_controller.reconcile_endpoints(inventory)
        except (RuntimeError, ValueError) as exc:
            self.statusBar().showMessage(f"Endpoint recovery check failed: {exc}", 10_000)

    @Slot(object, str)
    def _handle_call_bridge_capture_fault(self, role: EndpointRole, message: str) -> None:
        if self.call_bridge_controller is not None:
            self.call_bridge_controller.endpoint_lost(role)
        self.statusBar().showMessage(f"Call bridge capture muted: {message}", 15_000)

    @Slot(object)
    def _show_call_bridge_event(self, event: BridgeEvent) -> None:
        if event.kind is BridgeEventKind.STATE:
            self.call_bridge_panel.set_state(event.category)
        elif event.kind is BridgeEventKind.ERROR:
            if event.category == "playback_failure" and self.call_bridge_controller is not None:
                output_role = (
                    EndpointRole.CALL_MICROPHONE_RENDER
                    if event.lane_id is LaneId.OUTBOUND
                    else EndpointRole.LOCAL_HEADPHONES
                )
                self.call_bridge_controller.endpoint_lost(output_role)
            self.call_bridge_panel.set_state(BridgeState.DEGRADED, event.category)
            self.statusBar().showMessage(
                f"Call bridge {event.lane_id.value if event.lane_id else ''} failed closed: "
                f"{event.category}",
                15_000,
            )
        elif event.kind is BridgeEventKind.DROPPED:
            self.statusBar().showMessage(
                f"Call bridge dropped stale work: {event.category}", 10_000
            )
        elif event.kind is BridgeEventKind.ENDPOINT:
            self.call_bridge_panel.set_state(
                BridgeState.DEGRADED if event.category == "endpoint_lost" else BridgeState.RUNNING,
                event.message,
            )

    @Slot(object, float)
    def _show_call_bridge_level(self, role: EndpointRole, level: float) -> None:
        self.call_bridge_panel.set_level(role, level)

    @Slot(object)
    def _run_call_bridge_route_test(self, role: EndpointRole) -> None:
        if self.call_bridge_controller is not None:
            self._show_error("Stop the call bridge before running an isolated route test")
            return
        try:
            assignments = self.call_bridge_panel.assignments()
            endpoint = assignments[role]
        except Exception as exc:  # noqa: BLE001 - UI validation boundary.
            self._show_error(str(exc))
            return

        def run_test() -> None:
            language = (
                CALL_BRIDGE_REMOTE
                if role is EndpointRole.CALL_MICROPHONE_RENDER
                else CALL_BRIDGE_LOCAL
            )
            text = ROUTE_TEST_TEXT[language]
            path = None
            try:
                # Constructed on demand; the voice loads on its first synthesis.
                synthesizer = self.pipeline.voice_synthesizer()
                path = synthesizer.synthesize(text, language)
                EndpointPlaybackStream(endpoint).play(path)
                self.bridge.call_bridge_event.emit(
                    BridgeEvent(None, BridgeEventKind.ENDPOINT, "route_test_passed", role.value)
                )
            except Exception as exc:  # noqa: BLE001 - diagnostic boundary.
                self.bridge.call_bridge_event.emit(
                    BridgeEvent(
                        None, BridgeEventKind.ERROR, type(exc).__name__, "route_test_failed"
                    )
                )
            finally:
                if path is not None:
                    path.unlink(missing_ok=True)

        threading.Thread(target=run_test, name="call-bridge-route-test", daemon=True).start()

    def _submit_audio(self, utterance) -> None:
        self.runner.submit(utterance)

    @Slot(object)
    def _show_result(self, result: TranslationResult) -> None:
        name = self.pipeline.registry.display_name
        source, target = name(result.source_language), name(result.target_language)
        self.source_text.appendPlainText(f"{source}: {result.source_text}\n")
        self.target_text.appendPlainText(f"{target}: {result.translated_text}\n")
        direction = strings.ROUTING_FIXED.format(source=source, target=target)
        self.latency_label.setText(f"{direction} · Processing: {result.total_seconds:.2f} s")
        self.history.append(result)

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
        self.runner.resolve(held, LanguageId(language), on_done=self.bridge.held_resolved.emit)

    @Slot()
    def _held_resolved(self) -> None:
        self.held_turn_bar.set_resolving(False)
        self._refresh_held_bar()

    @Slot(object)
    def _discard_held(self, held: HeldTurn) -> None:
        """Drop the held turn and its audio: no result, no history, no export line."""
        self.pipeline.discard(held)
        self._refresh_held_bar()

    @Slot(str)
    def _show_error(self, message: str) -> None:
        self.statusBar().showMessage(message, 15_000)
        self.state_label.setText("Error")

    @Slot(bool)
    def _show_busy(self, busy: bool) -> None:
        self.state_label.setText(
            "Translating …" if busy else ("Listening …" if self.capture.running else "Ready")
        )

    @Slot(float)
    def _show_level(self, level: float) -> None:
        self.level_bar.setValue(round(level * 100))

    @Slot(bool)
    def _toggle_tts(self, enabled: bool) -> None:
        # The saved preference; a running session keeps the output it was started with.
        self.config.voice_output = enabled
        self._refresh_availability()

    @Slot()
    def _swap_direction(self) -> None:
        """Fixed source to the other member; Automatic to the first available direction."""
        pair = self.current_pair()
        if pair is None or self._session_locked():
            return
        current = self.current_fixed_source()
        candidates = pair.members if current is None else (pair.other(current),)
        model = self.mode_combo.model()
        for source in candidates:
            index = self.mode_combo.findData(source)
            if model.item(index).isEnabled():
                self.mode_combo.setCurrentIndex(index)
                return
        unavailable = model.item(self.mode_combo.findData(candidates[0])).toolTip()
        self.statusBar().showMessage(unavailable, 10_000)

    def write_transcript(self, path: Path) -> None:
        """Write the in-memory history as transcript v2 (UTF-8), ordered by capture time."""
        session = self.session_controller.session
        pair = session.pair if session is not None else self.current_pair()
        if pair is None:
            pair = self.pipeline.registry.pair(*self.config.languages.pair)
        Path(path).write_text(format_transcript_v2(pair, self.history), encoding="utf-8")

    @Slot()
    def _export_history(self) -> None:
        if not self.history:
            QMessageBox.information(self, "Transcript", "There is no conversation history yet.")
            return
        default = str(
            Path.home() / f"conversation-{dt.datetime.now().astimezone().date().isoformat()}.txt"
        )
        path, _ = QFileDialog.getSaveFileName(self, "Save transcript", default, "Text (*.txt)")
        if not path:
            return
        self.write_transcript(Path(path))
        self.statusBar().showMessage(f"Transcript saved: {path}", 10_000)

    def closeEvent(self, event: QCloseEvent) -> None:
        self.stop_call_bridge()
        self.stop_listening()
        if self.persist_settings:
            self.call_bridge_panel.apply_to_config()
            fixed_source = self.current_fixed_source()
            self.config.languages.routing = "bidirectional" if fixed_source is None else "fixed"
            # ``config.voice_output`` holds the user's preference, kept even while a
            # missing voice disables the checkbox.
            self.config.languages.fixed_source = fixed_source
            self.config.save()
        event.accept()
