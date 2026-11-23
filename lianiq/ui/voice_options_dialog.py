"""**Voice options…** of one language: Voice, Rate and Volume (CAP-0167 contract.md §7).

The dialog shows **Voice** only when the engine has more than one speaker, **Rate** iff the
engine supports it and **Volume** iff it supports it (``VoiceControls``). A sherpa-onnx voice
knows its speaker count only once it is loaded: with ``speakers is None`` and ``load_controls``
given, the dialog shows "Loading voice…" and calls ``load_controls`` on a worker thread, then
adds **Voice** if the voice has several speakers (AC-26). Each change is written through
``VoicePreferences.set_options`` and saved at once; the spoken output reads the options per
turn, so a running Conversation speaks its next turn with them (AC-16).
"""

from __future__ import annotations

import threading
from collections.abc import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from lianiq.config_voice import VoicePreferences
from lianiq.languages.registry import LanguageId, LanguageRegistry
from lianiq.tts.voice_controls import RATE_RANGE, VOLUME_RANGE, VoiceControls, VoiceOptions
from lianiq.ui import strings

STEP = 5  # the 0.05 UI step of Rate and Volume, in hundredths


def _slider(name: str, bounds: tuple[float, float], value: float) -> QSlider:
    slider = QSlider(Qt.Orientation.Horizontal)
    slider.setRange(round(bounds[0] * 100), round(bounds[1] * 100))
    slider.setSingleStep(STEP)
    slider.setPageStep(STEP)
    slider.setValue(round(value * 100))
    slider.setAccessibleName(name)
    return slider


class VoiceOptionsDialog(QDialog):
    changed = Signal(str)  # language ID: the options were changed and saved
    _loaded = Signal(object)  # VoiceControls, or None after a failed load (worker thread)

    def __init__(
        self,
        language: LanguageId,
        controls: VoiceControls,
        preferences: VoicePreferences,
        registry: LanguageRegistry,
        load_controls: Callable[[], VoiceControls] | None,
        parent: QWidget,
        save: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.language = language
        self.preferences = preferences
        self._save = save
        name = registry.display_name(language)
        self.setWindowTitle(strings.VOICE_OPTIONS_TITLE.format(language=name))
        self.setAccessibleName(strings.VOICE_OPTIONS_TITLE.format(language=name))
        options = preferences.options(language)
        self.form = QFormLayout()
        self.voice_combo: QComboBox | None = None
        self.rate_slider: QSlider | None = None
        self.volume_slider: QSlider | None = None
        self.loading = QLabel(strings.VOICE_LOADING)
        self.loading.setAccessibleName(strings.VOICE_LOADING)
        self.loading.setVisible(False)
        self.form.addRow(self.loading)
        self._add_voice(controls.speakers)
        if controls.rate:
            self.rate_slider, self.rate_value = self._add_slider(
                strings.VOICE_RATE, RATE_RANGE, options.rate
            )
        if controls.volume:
            self.volume_slider, self.volume_value = self._add_slider(
                strings.VOICE_VOLUME, VOLUME_RANGE, options.volume
            )
        self._show_values()
        buttons = QDialogButtonBox()
        close = buttons.addButton(strings.VOICE_CLOSE, QDialogButtonBox.ButtonRole.AcceptRole)
        close.setAccessibleName(strings.VOICE_CLOSE)
        buttons.accepted.connect(self.accept)
        layout = QVBoxLayout(self)
        layout.addLayout(self.form)
        layout.addWidget(buttons)
        self.load_thread: threading.Thread | None = None
        if controls.speakers is None and load_controls is not None:
            self._loaded.connect(self._show_loaded)
            self.loading.setVisible(True)
            self.load_thread = threading.Thread(
                target=self._load, args=(load_controls,), name="voice-options-load", daemon=True
            )
            self.load_thread.start()

    # Controls ------------------------------------------------------------------------------

    def _add_voice(self, speakers: int | None) -> None:
        """**Voice**: one entry per speaker (shown 1-based), only for several speakers."""
        if speakers is None or speakers <= 1 or self.voice_combo is not None:
            return
        combo = QComboBox()
        combo.setAccessibleName(strings.VOICE_CHOICE)
        for index in range(speakers):
            combo.addItem(strings.VOICE_SPEAKER.format(number=index + 1), index)
        chosen = self.preferences.options(self.language).speaker
        current = self._configured_speaker() if chosen is None else chosen
        combo.setCurrentIndex(min(max(current, 0), speakers - 1))
        combo.currentIndexChanged.connect(lambda _index: self._apply(speaker_chosen=True))
        self.voice_combo = combo
        self.form.insertRow(1, strings.VOICE_CHOICE, combo)

    def _configured_speaker(self) -> int:
        engine = self.preferences.config.tts.engines.get(self.language)
        return engine.speaker_id if engine is not None else 0

    def _add_slider(
        self, name: str, bounds: tuple[float, float], value: float
    ) -> tuple[QSlider, QLabel]:
        slider = _slider(name, bounds, value)
        text = QLabel()
        row = QHBoxLayout()
        row.addWidget(slider, 1)
        row.addWidget(text)
        caption = QLabel(name)
        caption.setBuddy(slider)
        self.form.addRow(caption, row)
        slider.valueChanged.connect(lambda _value: self._apply())
        return slider, text

    def _show_values(self) -> None:
        if self.rate_slider is not None:
            text = strings.VOICE_RATE_VALUE.format(value=self.rate_slider.value() / 100)
            self.rate_value.setText(text)
            self.rate_slider.setAccessibleDescription(text)
        if self.volume_slider is not None:
            text = strings.VOICE_VOLUME_VALUE.format(value=self.volume_slider.value())
            self.volume_value.setText(text)
            self.volume_slider.setAccessibleDescription(text)

    # Changes -------------------------------------------------------------------------------

    def options(self, *, speaker_chosen: bool = False) -> VoiceOptions:
        """The shown values; a control the engine lacks keeps the saved value."""
        saved = self.preferences.options(self.language)
        speaker = saved.speaker
        if speaker_chosen and self.voice_combo is not None:
            speaker = self.voice_combo.currentData()
        rate = saved.rate if self.rate_slider is None else self.rate_slider.value() / 100
        volume = saved.volume if self.volume_slider is None else self.volume_slider.value() / 100
        return VoiceOptions(speaker, rate, volume)

    def _apply(self, *, speaker_chosen: bool = False) -> None:
        self._show_values()
        self.preferences.set_options(self.language, self.options(speaker_chosen=speaker_chosen))
        if self._save is not None:
            self._save()
        self.changed.emit(str(self.language))

    # Lazy speaker count (sherpa-onnx) ----------------------------------------------------

    def _load(self, load_controls: Callable[[], VoiceControls]) -> None:
        try:
            controls = load_controls()
        except Exception:  # noqa: BLE001 - worker boundary: the dialog offers no Voice choice
            controls = None
        try:
            self._loaded.emit(controls)
        except RuntimeError:  # the dialog was deleted meanwhile
            pass

    def _show_loaded(self, controls: VoiceControls | None) -> None:
        self.loading.setVisible(False)
        if controls is not None:
            self._add_voice(controls.speakers)
