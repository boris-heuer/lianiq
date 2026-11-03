from __future__ import annotations

import datetime as dt
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
from lianiq.domain import ConversationMode, Language, TranslationResult
from lianiq.hardware import ctranslate2_cuda_available, resolve_compute_device
from lianiq.languages.modes import (
    CALL_BRIDGE_MODE,
    InputKind,
    OutputKind,
    RoutingKind,
    SessionPair,
    UsageMode,
)
from lianiq.pipeline import PipelineRunner, TranslationPipeline
from lianiq.ui.call_bridge_panel import CallBridgePanel

MODE_LABELS = {
    "Automatic": ConversationMode.AUTO,
    "German → Mandarin": ConversationMode.DE_TO_ZH,
    "Mandarin → German": ConversationMode.ZH_TO_DE,
}


class UiBridge(QObject):
    result = Signal(object)
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
        self.bridge.error.connect(self._show_error)
        self.bridge.busy.connect(self._show_busy)
        self.bridge.level.connect(self._show_level)
        self.bridge.session_ready.connect(self._session_ready)
        self.bridge.call_bridge_ready.connect(self._call_bridge_ready)
        self.bridge.call_bridge_event.connect(self._show_call_bridge_event)
        self.bridge.call_bridge_level.connect(self._show_call_bridge_level)
        self.bridge.call_bridge_capture_fault.connect(self._handle_call_bridge_capture_fault)
        self.history: list[tuple[str, str, str, str]] = []
        self.devices: list[AudioDevice] = []
        self.call_bridge_controller: FullDuplexBridgeController | None = None
        # Models are constructed and warmed on Start, for the started mode only.
        self._starting = False
        self._call_bridge_starting = False
        # Each Start gets a generation; a ready signal of a cancelled Start is ignored.
        self._start_generation = 0
        self._pending_assignments = None
        self._diagnostic_wav: Path | None = None
        self._endpoint_monitor = QTimer(self)
        self._endpoint_monitor.setInterval(2_000)
        self._endpoint_monitor.timeout.connect(self._reconcile_call_bridge_endpoints)

        self.setWindowTitle("lianiq · German ↔ Mandarin")
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
            mode_provider=self.current_mode,
            on_result=self.bridge.result.emit,
            on_error=self.bridge.error.emit,
            on_busy=self.bridge.busy.emit,
        )
        self.call_bridge_panel.set_models_ready(True)
        self.statusBar().showMessage("Models load on Start, only for the selected mode.")
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
        controls.addWidget(QLabel("Conversation direction"), 0, 0)
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(MODE_LABELS)
        initial_mode = ConversationMode(self.config.legacy_mode)
        self.mode_combo.setCurrentText(next(k for k, v in MODE_LABELS.items() if v is initial_mode))
        controls.addWidget(self.mode_combo, 1, 0)

        controls.addWidget(QLabel("Microphone"), 0, 1)
        self.input_combo = QComboBox()
        controls.addWidget(self.input_combo, 1, 1)
        controls.addWidget(QLabel("Speakers"), 0, 2)
        self.output_combo = QComboBox()
        controls.addWidget(self.output_combo, 1, 2)

        controls.addWidget(QLabel("Model profile"), 0, 3)
        self.model_combo = QComboBox()
        self.model_combo.addItem("Balanced · Whisper small + MarianMT", "balanced")
        self.model_combo.setToolTip("The installed profile is optimized for this EliteBook.")
        controls.addWidget(self.model_combo, 1, 3)

        self.tts_checkbox = QCheckBox("Voice output")
        self.tts_checkbox.setChecked(self.config.voice_output)
        self.tts_checkbox.toggled.connect(self._toggle_tts)
        controls.addWidget(self.tts_checkbox, 1, 4)
        self.gpu_checkbox = QCheckBox("CUDA GPU")
        recognition_device = self._recognition_device()
        self.gpu_checkbox.setChecked(recognition_device == "cuda")
        self.gpu_checkbox.setEnabled(False)
        runtime_device = recognition_device.upper()
        self.gpu_checkbox.setToolTip(f"Active inference device: {runtime_device}")
        controls.addWidget(self.gpu_checkbox, 1, 5)
        controls.setColumnStretch(1, 2)
        controls.setColumnStretch(2, 2)
        layout.addLayout(controls)

        action_row = QHBoxLayout()
        self.start_button = QPushButton("▶  Start  (F8)")
        self.start_button.setObjectName("primaryButton")
        self.start_button.clicked.connect(self.start_listening)
        self.stop_button = QPushButton("■  Stop  (F9)")
        self.stop_button.clicked.connect(self.stop_listening)
        self.stop_button.setEnabled(False)
        swap_button = QPushButton("⇄  Switch direction")
        swap_button.clicked.connect(self._swap_direction)
        export_button = QPushButton("Export transcript")
        export_button.clicked.connect(self._export_history)
        action_row.addWidget(self.start_button)
        action_row.addWidget(self.stop_button)
        action_row.addWidget(swap_button)
        action_row.addStretch()
        action_row.addWidget(export_button)
        layout.addLayout(action_row)

        self.call_bridge_panel = CallBridgePanel(self.config.call_bridge)
        self.call_bridge_panel.start_requested.connect(self.start_call_bridge)
        self.call_bridge_panel.stop_requested.connect(self.stop_call_bridge)
        self.call_bridge_panel.route_test_requested.connect(self._run_call_bridge_route_test)
        layout.addWidget(self.call_bridge_panel)

        splitter = QSplitter(Qt.Horizontal)
        source_panel, self.source_text = self._text_panel(
            "Original", "Speak in German or Mandarin …"
        )
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

    def current_mode(self) -> ConversationMode:
        return MODE_LABELS[self.mode_combo.currentText()]

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
        forced_source = self.current_mode().forced_source
        mode = UsageMode(
            InputKind.MICROPHONE,
            RoutingKind.BIDIRECTIONAL if forced_source is None else RoutingKind.FIXED,
            OutputKind.SPOKEN if self.tts_checkbox.isChecked() else OutputKind.TEXT,
        )
        return SessionPair(
            self.pipeline.registry.pair(*self.config.languages.pair),
            mode,
            fixed_source=forced_source.id if forced_source else None,
        )

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
        # Voice output may have been toggled while the models were loading.
        self.pipeline.set_voice_output(self.tts_checkbox.isChecked())
        if not ready:
            self._diagnostic_wav = None
            self.start_button.setEnabled(True)
            self.state_label.setText("Model error")
            self.statusBar().showMessage(message)
            return
        self._begin_listening()
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
        except Exception as exc:  # noqa: BLE001 - GUI boundary reports invalid selections.
            self._show_error(str(exc))
            return
        self._starting = True
        self.start_button.setEnabled(False)
        self.state_label.setText("Loading models …")
        self.statusBar().showMessage("Loading the models the selected mode requires …")
        self._prepare_in_background(session, self.bridge.session_ready)

    def _begin_listening(self) -> None:
        try:
            self.config.audio.input_device = self.input_combo.currentData()
            self.config.audio.output_device = self.output_combo.currentData()
            self.pipeline.output_device = self.config.audio.output_device
            self.runner.start()
            self.capture.start()
        except Exception as exc:  # noqa: BLE001 - GUI boundary reports dependency/device failures.
            self.start_button.setEnabled(True)
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
        self._diagnostic_wav = None
        self.capture.stop()
        self.runner.stop()
        self.start_button.setEnabled(not self._call_bridge_starting)
        self.stop_button.setEnabled(False)
        self.input_combo.setEnabled(True)
        self.output_combo.setEnabled(True)
        self.level_bar.setValue(0)
        self.state_label.setText("Ready")
        self.statusBar().showMessage("Capture stopped")

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
                validate_voice_files([Language.GERMAN.id, Language.MANDARIN.id])
            scheduler = InferenceScheduler(max_concurrent=2)
            outbound_playback = EndpointPlaybackStream(
                assignments[EndpointRole.CALL_MICROPHONE_RENDER]
            )
            inbound_playback = EndpointPlaybackStream(assignments[EndpointRole.LOCAL_HEADPHONES])
            outbound_lane = TranslationLane(
                LaneId.OUTBOUND,
                Language.GERMAN,
                Language.MANDARIN,
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
                Language.MANDARIN,
                Language.GERMAN,
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
        self.mode_combo.setEnabled(False)
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
        self.mode_combo.setEnabled(True)
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
                Language.MANDARIN
                if role is EndpointRole.CALL_MICROPHONE_RENDER
                else Language.GERMAN
            )
            text = "通话麦克风测试。" if language is Language.MANDARIN else "Kopfhörer-Test."
            path = None
            try:
                # Constructed on demand; the voice loads on its first synthesis.
                synthesizer = self.pipeline.voice_synthesizer()
                path = synthesizer.synthesize(text, language.id)
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
        source_name = "DE" if result.source_language is Language.GERMAN else "ZH"
        target_name = "DE" if result.target_language is Language.GERMAN else "ZH"
        self.source_text.appendPlainText(f"{source_name}: {result.source_text}\n")
        self.target_text.appendPlainText(f"{target_name}: {result.translated_text}\n")
        self.latency_label.setText(f"Processing: {result.total_seconds:.2f} s")
        timestamp = dt.datetime.now().astimezone().isoformat(timespec="seconds")
        self.history.append(
            (timestamp, result.source_text, result.translated_text, result.source_language.value)
        )

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
        self.config.voice_output = enabled
        self.pipeline.set_voice_output(enabled)

    @Slot()
    def _swap_direction(self) -> None:
        mode = self.current_mode()
        replacement = {
            ConversationMode.AUTO: ConversationMode.DE_TO_ZH,
            ConversationMode.DE_TO_ZH: ConversationMode.ZH_TO_DE,
            ConversationMode.ZH_TO_DE: ConversationMode.DE_TO_ZH,
        }[mode]
        self.mode_combo.setCurrentText(next(k for k, v in MODE_LABELS.items() if v is replacement))

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
        lines = []
        for timestamp, source, translated, language in self.history:
            target = "zh" if language == "de" else "de"
            lines.extend(
                [
                    f"[{timestamp}] {language.upper()}: {source}",
                    f"{target.upper()}: {translated}",
                    "",
                ]
            )
        Path(path).write_text("\n".join(lines), encoding="utf-8")
        self.statusBar().showMessage(f"Transcript saved: {path}", 10_000)

    def closeEvent(self, event: QCloseEvent) -> None:
        self.stop_call_bridge()
        self.stop_listening()
        if self.persist_settings:
            self.call_bridge_panel.apply_to_config()
            self.config.legacy_mode = self.current_mode().value
            self.config.voice_output = self.tts_checkbox.isChecked()
            self.config.save()
        event.accept()
