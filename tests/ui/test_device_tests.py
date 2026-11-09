"""**Test microphone** and **Test speakers** in Settings › Audio devices (CAP-0168 AC-18 UI).

Also AC-22a: no full refresh runs while a device test holds a stream; it runs after.
"""

from __future__ import annotations

import os
from typing import ClassVar

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from lianiq.ui import device_tests as device_tests_module
from lianiq.ui.shell.workspaces import WorkspaceId
from tests._fake_devices import SPEAKERS, FakeClock, mic
from tests._spy_window import spies  # noqa: F401
from tests.ui._language_helpers import start, wait_until
from tests.ui._notice_helpers import notice_window  # noqa: F401
from tests.ui.test_main_window_session import click


def settings(window):
    window.show_workspace(WorkspaceId.SETTINGS)
    setup = window.device_setup
    setup.clock = FakeClock()
    return setup


def test_ac18_test_microphone_without_signal_for_3_s_shows_no_signal(window) -> None:
    setup = settings(window)
    click(setup.test_mic_button)
    assert setup.testing and not setup.test_mic_button.isEnabled()
    assert setup.test_result.text() == "Listening to 'Test microphone' …"

    setup.test_level.emit(0.0)
    setup.clock.advance(2.9)
    setup.test_level.emit(0.0)
    assert setup.test_result.text() == "Listening to 'Test microphone' …"
    setup.clock.advance(0.2)
    setup.test_level.emit(0.0)
    assert setup.test_result.text() == (
        "No signal from 'Test microphone'. Check mute or choose another microphone."
    )
    assert setup._stop_timer.interval() == 5_000  # the test ends after at most 5 s
    setup.stop_microphone_test()
    assert not setup.testing and setup.test_mic_button.isEnabled()


def test_ac18_test_microphone_with_signal_moves_the_meter(window) -> None:
    setup = settings(window)
    click(setup.test_mic_button)
    setup.test_level.emit(0.5)
    assert setup.test_meter.value() == 50
    assert setup.test_result.text() == "Signal received from 'Test microphone'."
    setup.clock.advance(4.0)
    setup.test_level.emit(0.0)  # a pause after a signal is not "no signal"
    assert setup.test_result.text() == "Signal received from 'Test microphone'."
    setup.stop_microphone_test()
    assert setup.test_meter.value() == 0


class RecordingCapture:
    instances: ClassVar[list[RecordingCapture]] = []
    fail: ClassVar[bool] = False

    def __init__(self, _config, *, on_utterance, on_level=None):
        self.device, self.stopped = None, 0
        RecordingCapture.instances.append(self)

    def start(self):
        if RecordingCapture.fail:
            raise RuntimeError("Device unavailable")

    def stop(self):
        self.stopped += 1


def recording_capture(monkeypatch, *, fail: bool) -> list[RecordingCapture]:
    monkeypatch.setattr(RecordingCapture, "instances", [])
    monkeypatch.setattr(RecordingCapture, "fail", fail)
    monkeypatch.setattr(device_tests_module, "MicrophoneCapture", RecordingCapture)
    return RecordingCapture.instances


def test_ac18_ending_the_microphone_test_stops_its_stream(window, monkeypatch) -> None:
    captures = recording_capture(monkeypatch, fail=False)
    setup = settings(window)
    click(setup.test_mic_button)
    assert setup.testing and captures[0].stopped == 0
    setup.stop_microphone_test()
    assert captures[0].stopped == 1 and not setup.testing


def test_ac18_failed_microphone_test_releases_the_device(window, monkeypatch) -> None:
    captures = recording_capture(monkeypatch, fail=True)
    setup = settings(window)
    click(setup.test_mic_button)
    assert captures[0].stopped == 1 and not setup.testing
    assert setup.test_result.text() == "Test microphone could not start: Device unavailable"
    assert setup.test_mic_button.isEnabled()


def test_ac22a_no_full_refresh_while_a_test_holds_a_stream(window) -> None:
    setup, fake = settings(window), window.fake_devices
    click(setup.test_mic_button)
    headset = mic("USB Headset", 3, "headset")
    fake.set(*fake.endpoints, headset)
    click(setup.refresh_button)
    assert fake.reinitialized == 0 and window.input_combo.findData(headset.endpoint_id) == -1

    setup.stop_microphone_test()

    assert fake.reinitialized == 1 and window.input_combo.findData(headset.endpoint_id) > 0


def test_ac18_test_speakers_plays_the_tone_and_asks(window, monkeypatch) -> None:
    played = []

    def play(path, device, *, auto_convert=False):
        played.append((path.suffix, path.stat().st_size > 1_000, device, auto_convert))

    monkeypatch.setattr(device_tests_module, "play_wav", play)
    setup = settings(window)
    click(setup.test_speakers_button)

    assert wait_until(lambda: setup.heard_no.isVisible())
    assert played == [(".wav", True, SPEAKERS.runtime_index, True)]
    assert setup.test_result.text() == "Did you hear the tone from 'Test speakers'?"
    assert not setup.testing and setup.test_speakers_button.isEnabled()
    click(setup.heard_no)
    assert setup.test_result.text() == "Reconnect the device, or choose another one."
    assert not setup.heard_yes.isVisible()


def test_ac18_failed_tone_is_reported(window, monkeypatch) -> None:
    def fail(_path, _device, *, auto_convert=False):
        raise RuntimeError("Invalid device")

    monkeypatch.setattr(device_tests_module, "play_wav", fail)
    setup = settings(window)
    click(setup.test_speakers_button)
    assert wait_until(lambda: not setup.testing)
    assert setup.test_result.text() == "Test speakers could not start: Invalid device"
    assert not setup.heard_no.isVisible()


def test_ac18_both_tests_are_disabled_while_a_session_runs(window) -> None:
    setup = window.device_setup
    start(window)
    buttons = (setup.test_mic_button, setup.test_speakers_button)
    assert [button.isEnabled() for button in buttons] == [False, False]
    assert setup.test_mic_button.toolTip() == "Press Stop (F9) first. No other action is needed."
    setup.test_microphone()  # a programmatic request opens nothing
    assert not setup.testing
    window.stop_listening()
    assert [button.isEnabled() for button in buttons] == [True, True]
