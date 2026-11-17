"""The drain after **End meeting** keeps the session (CAP-0177 WI-04, AC-19).

``MeetingController.stop()`` drains for up to 120 s on a worker thread. Until it published
``STOPPED`` the owner stays *stopping*: Conversation (F8) and Call Bridge are refused with
the busy notice and open nothing, the strip shows "Meeting stopping…", and the GUI thread is
never blocked, also not by closing the window.
"""

from __future__ import annotations

import os
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from lianiq.languages.requirements import ModeAvailability
from lianiq.ui.shell.session_owner import SessionState
from lianiq.ui.shell.workspaces import WorkspaceId
from tests._spy_window import spies  # noqa: F401
from tests.ui._language_helpers import start
from tests.ui._meeting_window import (
    MEETING,
    assign_table,
    end_and_wait,
    meeting_window,  # noqa: F401
    notice_title,
    start_meeting,
)
from tests.ui.test_main_window_session import click, wait_until

CONVERSATION, CALL_BRIDGE = WorkspaceId.CONVERSATION, WorkspaceId.CALL_BRIDGE
BUSY = "Stop the Meeting session first"


def hold_stop(controller) -> tuple[threading.Event, list]:
    """``controller.stop`` waits until the returned event is set; records its thread."""
    release, threads = threading.Event(), []
    stop = controller.stop

    def held_stop(*args, **kwargs):
        threads.append(threading.current_thread())
        release.wait(10.0)
        return stop(*args, **kwargs)

    controller.stop = held_stop
    return release, threads


def draining(window) -> tuple[threading.Event, list]:
    assign_table(window)
    start_meeting(window)
    release, threads = hold_stop(window.meeting.controller)
    started = time.perf_counter()
    click(window.meeting.end_button)
    assert time.perf_counter() - started < 0.5  # the GUI thread is not blocked
    assert wait_until(lambda: threads != [])
    assert threads[0] is not threading.main_thread()
    return release, threads


def test_end_meeting_keeps_the_session_stopping_until_the_meeting_drained(window) -> None:
    release, _threads = draining(window)
    owner, meeting = window.session_owner, window.meeting
    assert owner.state is SessionState.STOPPING and owner.active is MEETING
    assert window.session_strip.state_label.text() == "Meeting stopping…"
    assert not window.stop_button.isEnabled()
    window.stop_active_session()  # F9 again: still draining, nothing changes
    assert owner.state is SessionState.STOPPING
    assert meeting.active() and not meeting.start_button.isEnabled()
    release.set()
    assert wait_until(lambda: owner.state is SessionState.IDLE)
    assert not meeting.active() and meeting.start_button.isEnabled()
    assert not window.session_strip.isVisible()


def test_conversation_and_call_bridge_are_refused_while_the_meeting_drains(
    window, monkeypatch
) -> None:
    import lianiq.ui.workspaces.call_bridge_lifecycle as lifecycle

    monkeypatch.setattr(lifecycle, "check_call_bridge", lambda *_: ModeAvailability(True, ()))
    monkeypatch.setattr(window.call_bridge_panel, "assignments", dict)
    release, _threads = draining(window)
    owner = window.session_owner
    generation = window.start_generation

    window.start_listening()  # F8
    assert notice_title(window, CONVERSATION) == BUSY and not window.capture.running
    window.start_call_bridge()
    assert notice_title(window, CALL_BRIDGE) == BUSY
    assert not window.call_bridge.starting and window.call_bridge_controller is None
    assert window.start_generation == generation  # no model warm-up was started
    assert owner.active is MEETING

    release.set()
    assert wait_until(lambda: owner.state is SessionState.IDLE)
    assert owner.busy_for(CONVERSATION) is None and owner.busy_for(CALL_BRIDGE) is None
    assert wait_until(lambda: notice_title(window, CONVERSATION) == "")
    start(window)  # allowed again
    assert owner.active is CONVERSATION
    window.stop_active_session()


def test_closing_the_window_while_the_meeting_drains_does_not_hang(
    tmp_path,
    spies,  # noqa: F811
    monkeypatch,
) -> None:
    from tests.ui._meeting_window import build_meeting_window

    window = build_meeting_window(tmp_path, monkeypatch)
    assign_table(window)
    start_meeting(window)
    release, threads = hold_stop(window.meeting.controller)
    started = time.perf_counter()
    window.close()
    assert time.perf_counter() - started < 0.5
    assert wait_until(lambda: threads != [])
    release.set()
    assert wait_until(lambda: window.session_owner.state is SessionState.IDLE)
    end_and_wait(window)
