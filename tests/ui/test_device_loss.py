"""Device loss, the identity monitor and the no-signal warning (CAP-0168 WI-04).

AC-19 and AC-20 (UI), AC-13 while running (``DEVICE_CHANGED``, refresh after Stop) and the
spec §2.3.5 10 s no-signal warning, over the D-07 fake devices and a fake clock.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from lianiq.audio.device_state import MONITOR_INTERVAL_MS
from lianiq.ui import notice_catalog as catalog
from tests._fake_devices import MICROPHONE, SPEAKERS, FakeClock, mic
from tests._spy_window import spies  # noqa: F401
from tests.ui._language_helpers import start, submit, transcript, wait_until
from tests.ui._notice_helpers import (
    CONVERSATION,
    action,
    notice_window,  # noqa: F401
    one_turn,
    shown,
)
from tests.ui.test_main_window_session import click


def test_session_opens_the_resolved_indices_and_runs_the_2_s_monitor(window) -> None:
    start(window)
    assert window.capture.device == MICROPHONE.runtime_index
    assert window.pipeline.output_device == SPEAKERS.runtime_index
    monitor = window.device_setup.monitor
    assert monitor.isActive() and monitor.interval() == MONITOR_INTERVAL_MS == 2_000
    window.stop_listening()
    assert wait_until(lambda: not monitor.isActive())


def test_ac13_while_running_changes_are_reported_and_refreshed_after_stop(window) -> None:
    setup, fake = window.device_setup, window.fake_devices
    start(window)
    headset = mic("USB Headset", 3, "headset")
    fake.set(MICROPHONE, SPEAKERS, headset)  # plugged in during the session

    click(setup.refresh_button)  # guarded: identities only

    notice = window.notices.get(catalog.DEVICES_CHANGED)
    assert notice.title == (
        "Audio devices changed: added 'USB Headset'. The running session keeps its devices."
    )
    assert fake.reinitialized == 0 and window.capture.running
    assert window.input_combo.findData(headset.endpoint_id) == -1  # lists unchanged
    assert not window.input_combo.isEnabled()

    window.stop_listening()

    assert wait_until(lambda: fake.reinitialized == 1)  # the full refresh after Stop
    assert window.input_combo.findData(headset.endpoint_id) > 0


def test_ac19_microphone_unplugged_stops_and_reconnect_reselects_it(window, spies) -> None:  # noqa: F811
    setup, fake = window.device_setup, window.fake_devices
    one_turn(window, spies)
    fake.unplug(MICROPHONE)

    setup.monitor_tick()

    assert not window.capture.running and window.session_owner.state.value == "idle"
    assert len(window.history) == 1 and "Guten Tag" in window.source_text.toPlainText()
    title, _detail, labels = shown(window)
    assert "Microphone 'Test microphone' disconnected." in title
    assert labels == ["Reconnect", "Choose device"]
    assert wait_until(lambda: fake.reinitialized == 1)  # the pending refresh after Stop
    assert not window.capture.running  # nothing restarts on its own

    fake.set(MICROPHONE, SPEAKERS)  # replugged
    click(action(window, "Reconnect"))

    assert window.notices.get(catalog.MICROPHONE_LOST) is None
    assert setup.resolved(MICROPHONE.flow).endpoint == MICROPHONE
    start(window)  # the user's Start succeeds on the same identity
    assert window.capture.device == MICROPHONE.runtime_index


def test_ac19_a_stream_fault_counts_as_microphone_lost(window) -> None:
    start(window)
    window.capture._stream = type("Stopped", (), {"active": False})()
    window.device_setup.monitor_tick()
    assert not window.capture.running
    assert window.notices.get(catalog.MICROPHONE_LOST) is not None


def test_ac20_speakers_unplugged_keep_capture_and_reconnect_after_stop(window, spies) -> None:  # noqa: F811
    setup, fake = window.device_setup, window.fake_devices
    window.mode_combo.setCurrentText("German → Mandarin (Simplified)")
    window.tts_checkbox.setChecked(True)
    start(window)
    fake.unplug(SPEAKERS)

    setup.monitor_tick()

    assert window.capture.running and window.pipeline.voice_output is False
    title, detail, labels = shown(window)
    assert "Speakers 'Test speakers' disconnected." in title
    assert "Recording continues. Spoken output stopped." in detail
    assert labels == ["Reconnect", "Choose device"]
    reconnect = action(window, "Reconnect")
    assert not reconnect.isEnabled() and reconnect.toolTip() == "Available after Stop"
    submit(window, spies, transcript("Guten Tag", "de"))
    assert wait_until(lambda: window.target_text.toPlainText().strip())  # still as text

    window.stop_listening()
    assert wait_until(lambda: fake.reinitialized == 1)
    assert reconnect.isEnabled()
    fake.set(MICROPHONE, SPEAKERS)  # replugged
    click(reconnect)

    assert fake.reinitialized == 2  # Reconnect always runs a full refresh
    assert window.notices.get(catalog.SPEAKERS_LOST) is None
    assert setup.resolved(SPEAKERS.flow).endpoint == SPEAKERS


def test_conversation_meter_warns_after_10_s_of_silence(window) -> None:
    setup = window.device_setup
    setup.clock = clock = FakeClock()
    start(window)

    for _ in range(10):  # 9 s of silence: no warning yet
        setup.conversation_level(0.0)
        clock.advance(0.9)
    assert window.notices.get(catalog.NO_SIGNAL) is None
    clock.advance(5.0)  # muted while spoken output played: not silence
    setup.conversation_level(0.0)
    assert window.notices.get(catalog.NO_SIGNAL) is None
    for _ in range(12):
        clock.advance(0.9)
        setup.conversation_level(0.0)

    notice = window.notices.get(catalog.NO_SIGNAL)
    assert notice.title == (
        "No signal from 'Test microphone'. Check mute or choose another microphone."
    )
    assert notice.severity.name == "WARNING" and notice.workspace is CONVERSATION
    assert window.capture.running  # a warning, the session continues
    setup.conversation_level(0.5)
    assert window.notices.get(catalog.NO_SIGNAL) is None
