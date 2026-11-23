"""CAP-0170 WI-05 (AC-14): microphone loss on the Listen page over the D-07 fake devices."""
# ruff: noqa: F811 - ``spies`` is the imported fixture

from __future__ import annotations

import threading

import pytest

pytest.importorskip("PySide6")

from lianiq.listen.lifecycle import ListenPhase
from lianiq.listen.transcript import SegmentState
from lianiq.ui import strings
from lianiq.ui.shell.workspaces import WorkspaceId
from lianiq.ui.workspaces.listen_selection import MISSING
from tests._fake_devices import MICROPHONE, SPEAKERS, mic
from tests._spy_window import spies  # noqa: F401 - the fixture
from tests.ui._language_packs_helpers import wait_until
from tests.ui._listen_helpers import listen_window, phase_is, speak, start, states
from tests.ui._notice_helpers import action
from tests.ui.test_main_window_accessibility import focused
from tests.ui.test_main_window_session import click

LISTEN = WorkspaceId.LISTEN
KEY = "listen.microphone-lost"
SECOND = mic("Second microphone", 2, "mic2")


@pytest.fixture
def window(tmp_path, monkeypatch, spies):
    window = listen_window(tmp_path, monkeypatch)
    yield window
    window.listen.shutdown()
    window.close()


def lost(window):
    return window.notices.get(KEY)


def one_row(window, spies) -> None:
    start(window)
    speak(window, spies, "Hallo.")
    assert wait_until(lambda: states(window) == [SegmentState.DONE])


def test_ac14_a_stream_error_stops_keeps_rows_and_names_the_device(window, spies) -> None:
    one_row(window, spies)
    capture = window.listen_captures[-1]
    error = threading.Thread(target=capture.on_error, args=("PortAudio error -9999",))
    error.start()
    error.join()
    assert phase_is(window, ListenPhase.IDLE)
    assert states(window) == [SegmentState.DONE]  # the rows stay
    assert wait_until(lambda: lost(window) is not None)
    notice = lost(window)
    assert notice.title == strings.LISTEN_MIC_LOST.format(device="Test microphone")
    assert [item.label for item in notice.actions] == ["Reconnect", "Choose device"]
    assert "PortAudio" not in notice.title + notice.detail
    assert len(window.listen_captures) == 1 and not capture.running  # nothing restarts


def test_ac14_removal_reconnect_and_the_next_start(window, spies) -> None:
    one_row(window, spies)
    window.fake_devices.unplug(MICROPHONE)
    window.device_setup.monitor_tick()  # the 2 s identity monitor
    assert phase_is(window, ListenPhase.IDLE)
    assert wait_until(lambda: lost(window) is not None)
    assert states(window) == [SegmentState.DONE]

    click(action(window, "Reconnect", LISTEN))  # still unplugged: the same notice again
    assert lost(window) is not None and lost(window).repeats == 1
    assert window.listen.microphone_combo.currentData() != MICROPHONE.endpoint_id

    window.fake_devices.set(MICROPHONE, SPEAKERS)  # replugged
    click(action(window, "Reconnect", LISTEN))
    assert lost(window) is None
    assert window.listen.start_button.isEnabled()
    start(window)  # the next Start opens the same microphone
    assert len(window.listen_captures) == 2
    assert window.listen_captures[-1].device == MICROPHONE.runtime_index


def test_ac14_choose_device_focuses_the_microphone_selector(window, spies) -> None:
    one_row(window, spies)
    window.fake_devices.unplug(MICROPHONE)
    window.device_setup.monitor_tick()
    assert wait_until(lambda: lost(window) is not None)
    window.show_workspace(WorkspaceId.CONVERSATION)
    window.show_workspace(LISTEN)
    click(action(window, "Choose device", LISTEN))
    assert window.current_workspace() is LISTEN
    assert wait_until(lambda: focused() is window.listen.microphone_combo)


def test_ac14_another_microphone_is_never_chosen(tmp_path, monkeypatch, spies) -> None:
    def configure(config, _root) -> None:
        config.listen.input_policy = "explicit"
        config.listen.input_endpoint_id = MICROPHONE.endpoint_id

    window = listen_window(tmp_path, monkeypatch, configure=configure)
    try:
        window.fake_devices.set(MICROPHONE, SECOND, SPEAKERS)
        window.device_setup.load()
        window.listen.refresh()
        one_row(window, spies)
        window.fake_devices.unplug(MICROPHONE)
        window.device_setup.monitor_tick()
        assert phase_is(window, ListenPhase.IDLE)
        assert wait_until(lambda: lost(window) is not None)
        click(action(window, "Reconnect", LISTEN))  # SECOND is present but never taken
        assert lost(window) is not None
        assert window.listen.microphone_combo.currentData() == MISSING
        assert not window.listen.start_button.isEnabled()
        assert window.config.listen.input_endpoint_id == MICROPHONE.endpoint_id
    finally:
        window.listen.shutdown()
        window.close()
