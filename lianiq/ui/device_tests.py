"""**Test microphone** and **Test speakers** of ``DeviceSetup`` (CAP-0168 spec §2.3.5, AC-18).

- **Test microphone** opens the selected microphone for at most 5 s and drives the meter;
  3 s without signal shows ``DEVICE_NO_SIGNAL``.
- **Test speakers** plays a 1 s local tone on the selected speakers, then asks
  ``DEVICE_SPEAKER_TEST_DONE``; **No** shows the choose-device hint.

Both open a stream, so they are disabled while a session runs, and no full refresh runs
while a test is open. ``MicrophoneCapture`` and ``play_wav`` are looked up on this module.
"""

from __future__ import annotations

import os
import tempfile
import threading
import wave
from pathlib import Path

import numpy as np
from PySide6.QtCore import QTimer, Slot
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QProgressBar, QPushButton

from lianiq.audio.capture import MicrophoneCapture
from lianiq.audio.playback import play_wav
from lianiq.call_bridge.contracts import EndpointFlow
from lianiq.ui import strings

CAPTURE, RENDER = EndpointFlow.CAPTURE, EndpointFlow.RENDER
MIC_TEST_SECONDS = 5.0
MIC_NO_SIGNAL_SECONDS = 3.0
TONE_SECONDS, TONE_HZ, TONE_RATE = 1.0, 440.0, 16_000
NO_SIGNAL_LEVEL = 0.02


def write_tone(path: Path) -> Path:
    """A 1 s, 440 Hz mono PCM16 tone (local; nothing is downloaded)."""
    times = np.arange(round(TONE_SECONDS * TONE_RATE)) / TONE_RATE
    samples = (0.2 * np.sin(2 * np.pi * TONE_HZ * times) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(TONE_RATE)
        wav.writeframes(samples.tobytes())
    return path


class DeviceTests:
    def init_tests(self) -> None:
        self._test_capture: MicrophoneCapture | None = None
        self._test_started = 0.0
        self._test_signal = False
        self._stop_timer = QTimer(self, singleShot=True, interval=int(MIC_TEST_SECONDS * 1000))
        self._stop_timer.timeout.connect(self.stop_microphone_test)
        self._signal_timer = QTimer(
            self, singleShot=True, interval=int(MIC_NO_SIGNAL_SECONDS * 1000)
        )
        self._signal_timer.timeout.connect(self._check_test_signal)
        self.test_level.connect(self._test_level)
        self.tone_done.connect(self._tone_done)

    def build_tests(self, buttons: QHBoxLayout, grid: QGridLayout, row: int) -> None:
        self.test_mic_button = QPushButton(strings.DEVICE_TEST_MIC)
        self.test_speakers_button = QPushButton(strings.DEVICE_TEST_SPEAKERS)
        self.test_mic_button.clicked.connect(self.test_microphone)
        self.test_speakers_button.clicked.connect(self.test_speakers)
        self.test_meter = QProgressBar()
        self.test_meter.setRange(0, 100)
        self.test_meter.setTextVisible(False)
        self.test_meter.setAccessibleName(strings.DEVICE_TEST_MIC)
        self.test_result = QLabel()
        self.test_result.setWordWrap(True)
        self.heard_yes = QPushButton(strings.DEVICE_YES)
        self.heard_no = QPushButton(strings.DEVICE_NO)
        self.heard_yes.clicked.connect(lambda: self._heard(True))
        self.heard_no.clicked.connect(lambda: self._heard(False))
        for button in (self.test_mic_button, self.test_speakers_button):
            button.setAccessibleName(button.text())
            buttons.addWidget(button)
        buttons.addWidget(self.test_meter, 1)
        result = QHBoxLayout()
        result.addWidget(self.test_result, 1)
        for button in (self.heard_yes, self.heard_no):
            button.setAccessibleName(button.text())
            button.hide()
            result.addWidget(button)
        grid.addLayout(result, row, 0, 1, 2)

    def set_tests_enabled(self, idle: bool) -> None:
        """The tests are disabled while a session runs (and while one test is open)."""
        for button in (self.test_mic_button, self.test_speakers_button):
            button.setEnabled(idle and not self.testing)
            button.setToolTip("" if idle else strings.DETAIL_LOCKED)

    def _session_idle(self) -> bool:
        return not self.host.session_locked()

    # Test microphone --------------------------------------------------------------------

    @Slot()
    def test_microphone(self) -> None:
        if self.streams_open():
            return
        resolved = self.resolved(CAPTURE)
        if resolved.endpoint is None:
            self.test_result.setText(resolved.label)
            return
        capture = MicrophoneCapture(
            self.config.audio, on_utterance=lambda _utterance: None, on_level=self.test_level.emit
        )
        capture.device = resolved.endpoint.runtime_index
        try:
            capture.start()
        except Exception as exc:  # noqa: BLE001 - the device boundary reports every open error.
            capture.stop()
            reason = strings.NOTICE_START_FAILED.format(mode=strings.DEVICE_TEST_MIC, reason=exc)
            self.test_result.setText(reason)
            return
        self._test_capture, self.testing = capture, True
        self._test_started, self._test_signal = self.clock(), False
        self.test_result.setText(strings.DEVICE_TESTING.format(name=self.device_name(CAPTURE)))
        self.set_tests_enabled(self._session_idle())
        self.monitor.start()
        self._stop_timer.start()
        self._signal_timer.start()

    @Slot(float)
    def _test_level(self, level: float) -> None:
        if self._test_capture is None:
            return
        self.test_meter.setValue(round(level * 100))
        if level >= NO_SIGNAL_LEVEL:
            self._test_signal = True
            self.test_result.setText(
                strings.DEVICE_SIGNAL_OK.format(name=self.device_name(CAPTURE))
            )
        else:
            self._check_test_signal()

    @Slot()
    def _check_test_signal(self) -> None:
        if self._test_capture is None or self._test_signal:
            return
        if self.clock() - self._test_started >= MIC_NO_SIGNAL_SECONDS:
            self.test_result.setText(
                strings.DEVICE_NO_SIGNAL.format(name=self.device_name(CAPTURE))
            )

    @Slot()
    def stop_microphone_test(self) -> None:
        capture, self._test_capture = self._test_capture, None
        self._stop_timer.stop()
        self._signal_timer.stop()
        if capture is not None:
            capture.stop()
        self.test_meter.setValue(0)
        self._test_finished()

    def _test_finished(self) -> None:
        self.testing = False
        self.set_tests_enabled(self._session_idle())
        self.streams_closed()

    # Test speakers ----------------------------------------------------------------------

    @Slot()
    def test_speakers(self) -> None:
        if self.streams_open():
            return
        resolved = self.resolved(RENDER)
        if resolved.endpoint is None:
            self.test_result.setText(resolved.label)
            return
        handle, name = tempfile.mkstemp(prefix="lianiq-tone-", suffix=".wav")
        os.close(handle)
        path, index = write_tone(Path(name)), resolved.endpoint.runtime_index
        self.testing = True
        self.set_tests_enabled(self._session_idle())
        for button in (self.heard_yes, self.heard_no):
            button.hide()
        self.test_result.setText("")

        def play() -> None:
            reason = ""
            try:
                play_wav(path, index, auto_convert=True)
            except Exception as exc:  # noqa: BLE001 - reported in the Settings page.
                reason = str(exc) or type(exc).__name__
            finally:
                path.unlink(missing_ok=True)
            self.tone_done.emit(reason)

        threading.Thread(target=play, name="speaker-test", daemon=True).start()

    @Slot(str)
    def _tone_done(self, reason: str) -> None:
        if reason:
            mode = strings.DEVICE_TEST_SPEAKERS
            self.test_result.setText(strings.NOTICE_START_FAILED.format(mode=mode, reason=reason))
        else:
            name = self.device_name(RENDER)
            self.test_result.setText(strings.DEVICE_SPEAKER_TEST_DONE.format(name=name))
            for button in (self.heard_yes, self.heard_no):
                button.show()
        self._test_finished()

    def _heard(self, heard: bool) -> None:
        for button in (self.heard_yes, self.heard_no):
            button.hide()
        self.test_result.setText("" if heard else strings.DETAIL_DEVICE)
