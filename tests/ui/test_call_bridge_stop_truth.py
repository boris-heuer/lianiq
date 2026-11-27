"""Call Bridge Stop off the GUI thread, lane timeout state and late results (AC-19).

session-status-truthfulness WI-05 (spec §2.2.2, §2.2.4): F9 and **Stop call bridge** go
through ``owner.stop()``; both lanes stop in parallel on a worker while a 50 ms ``QTimer``
keeps firing. A hung lane spy with a shortened bound reads *Did not stop in time*,
``session.stop-timeout`` shows and the lingering guard (AC-05) refuses Start until the lane
has exited. A late lane result is not shown.
"""

from __future__ import annotations

import os
import threading
import time
from datetime import datetime
from uuid import uuid4

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from lianiq.call_bridge.contracts import LaneId
from lianiq.domain import TranslationResult
from lianiq.ui import notice_catalog as catalog
from lianiq.ui import strings
from lianiq.ui.shell.session_owner import SessionState
from lianiq.ui.shell.workspaces import WorkspaceId
from lianiq.ui.strings_session import LANE_DID_NOT_STOP
from tests._spy_window import spies  # noqa: F401
from tests.ui._call_bridge_window import (
    assign,
    call_bridge_window,  # noqa: F401
    click,
    wait_until,
)

CALL_BRIDGE = WorkspaceId.CALL_BRIDGE
OUT, IN = LaneId.OUTBOUND, LaneId.INBOUND


def statuses(window) -> tuple[str, str]:
    paths = window.call_bridge_panel.paths
    return paths[OUT].status_label.text(), paths[IN].status_label.text()


def start(window) -> None:
    assign(window)
    click(window.call_bridge_panel.start_button)
    assert wait_until(lambda: window.call_bridge_controller is not None)
    assert window.session_owner.state is SessionState.RUNNING


def ticker(window):
    """A 50 ms ``QTimer`` on the GUI thread; the returned list grows with every tick."""
    from PySide6.QtCore import QTimer

    ticks: list[float] = []
    timer = QTimer(window)
    timer.setInterval(50)
    timer.timeout.connect(lambda: ticks.append(time.monotonic()))
    timer.start()
    return timer, ticks


def slow_stop(lane, seconds: float, calls: list) -> None:
    """``lane.stop`` takes ``seconds`` and records its thread and start/end times."""
    original = lane.stop

    def stop(timeout: float = 10.0) -> bool:
        began = time.monotonic()
        time.sleep(seconds)
        calls.append((threading.current_thread(), began, time.monotonic(), timeout))
        return original(timeout=timeout)

    lane.stop = stop


def hung_stop(lane, release: threading.Event) -> None:
    """``lane.stop`` does not return until ``release`` is set; then the lane really stops."""
    original = lane.stop

    def stop(timeout: float = 10.0) -> bool:
        release.wait(10.0)
        return original(timeout=timeout)

    lane.stop = stop


def press_f9(window) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    QTest.keyClick(window, Qt.Key.Key_F9)


def strip_reads_stopping(window) -> bool:
    expected = strings.SESSION_STOPPING.format(mode="Call Bridge")
    return window.session_strip.state_label.text() == expected


def test_ac19_f9_stops_both_lanes_in_parallel_on_a_worker(window) -> None:
    start(window)
    controller = window.call_bridge_controller
    calls: list = []
    slow_stop(controller.outbound_lane, 0.4, calls)
    slow_stop(controller.inbound_lane, 0.4, calls)
    timer, ticks = ticker(window)

    began = time.monotonic()
    press_f9(window)

    assert time.monotonic() - began < 0.2  # F9 returned at once: the GUI was not blocked
    assert window.session_owner.state is SessionState.STOPPING
    assert strip_reads_stopping(window)
    assert wait_until(lambda: window.session_owner.state is SessionState.IDLE)
    timer.stop()
    assert len(ticks) >= 5  # the 50 ms timer kept firing during the 0.4 s lane stop
    assert len(calls) == 2
    assert all(thread is not threading.main_thread() for thread, *_ in calls)
    (_, began_a, ended_a, timeout), (_, began_b, ended_b, _) = calls
    assert began_a < ended_b and began_b < ended_a  # both lanes stopped at the same time
    assert timeout == 10.0  # the per-lane bound
    assert statuses(window) == ("Stopped", "Stopped")
    assert window.notices.get(catalog.STOP_TIMEOUT_KEY) is None
    assert window.session_owner.lingering() is None


@pytest.mark.parametrize("via", ["f9", "page"])
def test_ac19_a_hung_lane_reads_did_not_stop_in_time_and_lingers(window, via) -> None:
    start(window)
    workspace = window.call_bridge
    workspace.lane_stop_timeout = 0.2  # the 10 s bound, shortened through the parameter
    controller = window.call_bridge_controller
    release = threading.Event()
    hung_stop(controller.outbound_lane, release)
    timer, ticks = ticker(window)
    try:
        if via == "f9":
            press_f9(window)
        else:
            click(window.call_bridge_panel.stop_button)  # through owner.stop(), too
        assert window.session_owner.state is SessionState.STOPPING
        assert strip_reads_stopping(window)
        assert wait_until(lambda: window.session_owner.state is SessionState.IDLE)
        assert len(ticks) >= 3  # the GUI kept running while the lane hung

        assert statuses(window) == (LANE_DID_NOT_STOP, "Stopped")
        notice = window.notices.get(catalog.STOP_TIMEOUT_KEY)
        assert notice is not None and notice.workspace is CALL_BRIDGE
        assert "Stopped" not in statuses(window)[0]

        # AC-05: every Start is refused while the hung lane is alive.
        assert window.session_owner.lingering() is CALL_BRIDGE
        click(window.call_bridge_panel.start_button)
        assert window.notices.get(catalog.STILL_FINISHING_KEY) is not None
        assert window.call_bridge_controller is None
        assert window.session_owner.state is SessionState.IDLE

        release.set()
        assert wait_until(lambda: not controller.alive())
        assert window.session_owner.lingering() is None
    finally:
        release.set()
        timer.stop()


def result_for(window, lane: LaneId) -> TranslationResult:
    from lianiq.call_bridge.contracts import CallBridgeLanes

    edge = CallBridgeLanes.from_session(window.call_bridge.session()).edge(lane)
    return TranslationResult(
        uuid4(),
        datetime.now().astimezone(),
        "Guten Tag",
        "你好",
        edge.source,
        edge.target,
        0.1,
        0.1,
    )


def test_ac19_a_late_lane_result_is_not_shown(window) -> None:
    start(window)
    view = window.call_bridge_panel.text_view
    generation = window.call_bridge.lane_status.generation
    window.bridge.call_bridge_result.emit(generation - 1, result_for(window, OUT))  # stale
    assert view.turns() == []
    window.bridge.call_bridge_result.emit(generation, result_for(window, OUT))
    assert len(view.turns()) == 1

    window.call_bridge.lane_stop_timeout = 0.2
    release = threading.Event()
    hung_stop(window.call_bridge_controller.inbound_lane, release)
    try:
        press_f9(window)
        assert wait_until(lambda: window.session_owner.state is SessionState.IDLE)
        assert statuses(window) == ("Stopped", LANE_DID_NOT_STOP)
        # The hung lane finishes its turn after the bridge ended: the result is dropped.
        window.bridge.call_bridge_result.emit(generation, result_for(window, IN))
        assert len(view.turns()) == 1
    finally:
        release.set()
