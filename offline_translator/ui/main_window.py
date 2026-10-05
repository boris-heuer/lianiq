from __future__ import annotations

import datetime as dt
import sys
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal, Slot
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

from offline_translator.audio.capture import MicrophoneCapture
from offline_translator.audio.devices import AudioDevice, list_audio_devices
from offline_translator.audio.wav import read_pcm16_mono
from offline_translator.config import AppConfig
from offline_translator.domain import ConversationMode, Language, TranslationResult
from offline_translator.pipeline import PipelineRunner, TranslationPipeline

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
    models_ready = Signal(bool, str)


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
        self.bridge.models_ready.connect(self._models_ready)
        self.history: list[tuple[str, str, str, str]] = []
        self.devices: list[AudioDevice] = []

        self.setWindowTitle("Offline Interpreter · German ↔ Mandarin")
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
        self.start_button.setEnabled(False)
        self.state_label.setText("Loading models …")
        self.statusBar().showMessage("Loading all offline models into memory …")
        threading.Thread(target=self._warm_models, name="model-warmup", daemon=True).start()

        QShortcut(QKeySequence("F8"), self, activated=self.start_listening)
        QShortcut(QKeySequence("F9"), self, activated=self.stop_listening)

    def _build_ui(self) -> None:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(16)

        title_row = QHBoxLayout()
        title = QLabel("Offline Interpreter")
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
        initial_mode = ConversationMode(self.config.ui.mode)
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
        self.tts_checkbox.setChecked(self.config.tts.enabled)
        self.tts_checkbox.toggled.connect(self._toggle_tts)
        controls.addWidget(self.tts_checkbox, 1, 4)
        self.gpu_checkbox = QCheckBox("CUDA GPU")
        self.gpu_checkbox.setChecked(getattr(self.pipeline.recognizer, "device", "cpu") == "cuda")
        self.gpu_checkbox.setEnabled(False)
        runtime_device = getattr(self.pipeline.recognizer, "device", "cpu").upper()
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

    def _warm_models(self) -> None:
        try:
            self.pipeline.warm_up()
        except Exception as exc:  # noqa: BLE001 - background boundary reports model failures.
            self.bridge.models_ready.emit(False, str(exc))
        else:
            self.bridge.models_ready.emit(True, "")

    @Slot(bool, str)
    def _models_ready(self, ready: bool, message: str) -> None:
        self.start_button.setEnabled(ready)
        self.state_label.setText("Ready" if ready else "Model error")
        self.statusBar().showMessage(
            "All models are loaded; offline capture is ready." if ready else message
        )
        if not ready:
            return
        if "--diagnostic-wav" in sys.argv:
            argument_index = sys.argv.index("--diagnostic-wav") + 1
            if argument_index >= len(sys.argv):
                self._show_error("--diagnostic-wav requires a WAV file path")
                return
            self.start_listening()
            threading.Thread(
                target=self._submit_diagnostic_wav,
                args=(Path(sys.argv[argument_index]),),
                name="diagnostic-wav-input",
                daemon=True,
            ).start()
        elif "--diagnostic-auto-start" in sys.argv:
            self.start_listening()

    def _submit_diagnostic_wav(self, path: Path) -> None:
        try:
            utterance = read_pcm16_mono(path, self.config.audio.sample_rate)
            self.runner.submit(utterance)
        except Exception as exc:  # noqa: BLE001 - diagnostic boundary reports all failures.
            self.bridge.error.emit(f"Diagnostic WAV failed: {exc}")

    @Slot()
    def start_listening(self) -> None:
        try:
            self.config.audio.input_device = self.input_combo.currentData()
            self.config.audio.output_device = self.output_combo.currentData()
            self.pipeline.output_device = self.config.audio.output_device
            self.runner.start()
            self.capture.start()
        except Exception as exc:  # noqa: BLE001 - GUI boundary reports dependency/device failures.
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
        self.capture.stop()
        self.runner.stop()
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.input_combo.setEnabled(True)
        self.output_combo.setEnabled(True)
        self.level_bar.setValue(0)
        self.state_label.setText("Ready")
        self.statusBar().showMessage("Capture stopped")

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
        self.config.tts.enabled = enabled
        self.pipeline.synthesizer = (
            getattr(self, "_synthesizer", self.pipeline.synthesizer) if enabled else None
        )

    def set_synthesizer_reference(self, synthesizer) -> None:
        self._synthesizer = synthesizer

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
        self.stop_listening()
        if self.persist_settings:
            self.config.ui.mode = self.current_mode().value
            self.config.tts.enabled = self.tts_checkbox.isChecked()
            self.config.save()
        event.accept()
