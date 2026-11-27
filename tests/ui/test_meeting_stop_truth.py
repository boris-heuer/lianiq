"""Meeting page stop states, kept rows and the controller generation (session-status-truthfulness).

Offscreen UI tests over the real ``MeetingController`` on synthetic adapters
(``_meeting_window.py``). A held recogniser keeps one contribution translating; the drain
bounds are shortened through ``MeetingWorkspace.drain_bounds`` (AC-15..AC-18, AC-06).
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from lianiq.meeting.events import MeetingEvent, MeetingEventKind, MeetingLine
from lianiq.ui.shell.session_owner import SessionState
from tests._spy_window import spies  # noqa: F401
from tests.meeting.support import say
from tests.ui._meeting_window import (
    MEETING,
    TABLE,
    USER,
    assign_table,
    end_and_wait,
    meeting_window,  # noqa: F401
    notice_title,
    start_meeting,
)
from tests.ui.test_main_window_session import click, wait_until

Kind = MeetingEventKind
NOT_TRANSLATED = "Table: Not translated — stopped before it was finished."


def _failing_stream(**_kwargs):
    raise OSError("The device is in use")


def label(window) -> str:
    return window.meeting.state_label.text()


def view_lines(window) -> list[str]:
    text = window.meeting.running_view.text.toPlainText()
    return text.split("\n") if text else []


def held(window) -> threading.Event:
    """The next recognition waits until the returned event is set (at most 10 s)."""
    window.meeting_factory.recognizer.hold = hold = threading.Event()
    return hold


def translating(window, *contributions) -> threading.Event:
    """A running meeting whose first of ``contributions`` is being recognised."""
    assign_table(window)
    start_meeting(window)
    hold = held(window)
    controller = window.meeting.controller
    for role, tag in contributions:
        say(controller, role, tag)
    assert wait_until(lambda: controller.unfinished() == len(contributions))
    assert wait_until(lambda: window.meeting_factory.recognizer.hold is None)  # in flight
    return hold


def test_ac15_fresh_launch_reads_ready(window) -> None:
    assign_table(window)
    assert label(window) == "Ready"


@pytest.mark.parametrize("how", ["end_meeting", "f9"])
def test_ac15_draining_counts_contributions_then_meeting_ended(window, how) -> None:
    hold = translating(window, (TABLE, 10))
    meeting = window.meeting
    started = time.perf_counter()
    if how == "f9":
        window.stop_active_session()
    else:
        click(meeting.end_button)
    assert time.perf_counter() - started < 0.1
    assert label(window) == "Stopping — finishing 1 contribution…"
    assert not meeting.end_button.isEnabled() and not meeting.start_button.isEnabled()
    assert window.session_owner.state is SessionState.STOPPING
    # AC-06: the captures are closed: no input reads Listening, the page never does.
    assert all(state.text() == "" for state in meeting.input_states.values())
    meeting.meeting_event.emit(MeetingEvent(Kind.LISTENING, TABLE, generation=meeting._generation))
    assert meeting.input_states[TABLE].text() == ""
    assert "Listening" not in label(window)
    hold.set()
    assert wait_until(lambda: window.session_owner.state is SessionState.IDLE)
    assert label(window) == "Meeting ended · 1 contribution"
    assert view_lines(window) == ["Table: Hallo, willkommen"]
    end_and_wait(window)


def test_ac15_the_count_follows_the_drain(window) -> None:
    hold = translating(window, (TABLE, 10), (TABLE, 11), (USER, 20))
    click(window.meeting.end_button)
    assert label(window) == "Stopping — finishing 3 contributions…"
    hold.set()
    assert wait_until(lambda: window.session_owner.state is SessionState.IDLE)
    assert label(window) == "Meeting ended · 3 contributions"
    end_and_wait(window)


@pytest.mark.parametrize("failure", ["no_controller", "device"])
def test_ac16_a_failed_start_reads_could_not_start_while_its_notice_is_open(
    window, failure
) -> None:
    assign_table(window)
    if failure == "no_controller":
        window.meeting_factory = None
    else:
        window.meeting_factory.streams = _failing_stream
    click(window.meeting.start_button)
    assert wait_until(lambda: notice_title(window, MEETING) != "")
    assert label(window) == "Could not start — see notice"
    window.meeting.refresh()  # an availability refresh keeps it
    assert label(window) == "Could not start — see notice"
    window.notices.resolve(window.notices.top(MEETING).key)
    assert label(window) == "Ready"


def test_after_a_meeting_a_failed_start_never_falls_back_to_ready(window) -> None:
    assign_table(window)
    start_meeting(window)
    end_and_wait(window)
    assert label(window) == "Meeting ended · 0 contributions"
    window.meeting_factory = None
    click(window.meeting.start_button)
    assert wait_until(lambda: notice_title(window, MEETING) != "")
    assert label(window) == "Could not start — see notice"
    window.notices.resolve(window.notices.top(MEETING).key)
    assert label(window) == "Meeting ended · 0 contributions"


def test_ac17_a_drain_timeout_keeps_the_rows_and_reports_the_loss(window) -> None:
    hold = translating(window, (TABLE, 10), (TABLE, 11))
    meeting, owner = window.meeting, window.session_owner
    meeting.drain_bounds = (0.2, 0.05)
    click(meeting.end_button)
    assert wait_until(lambda: owner.state is SessionState.IDLE)
    assert view_lines(window) == [NOT_TRANSLATED, NOT_TRANSLATED]  # no row vanished
    assert label(window) == "Stopped — 2 not finished"
    notice = window.notices.get("session.stop-timeout")
    assert notice is not None and "2 turns were not finished" in notice.title
    # The worker still hangs: every start is refused until it exits (AC-05).
    assert owner.lingering() is MEETING
    controllers = len(window.meeting_factory.controllers)
    click(meeting.start_button)
    assert "still finishing" in notice_title(window, MEETING)
    assert len(window.meeting_factory.controllers) == controllers and not meeting.active()
    hold.set()
    assert wait_until(lambda: owner.lingering() is None)
    assert view_lines(window) == [NOT_TRANSLATED, NOT_TRANSLATED]  # its late line is dropped
    start_meeting(window)
    end_and_wait(window)


def test_ac18_events_of_the_previous_controller_change_nothing(window) -> None:
    assign_table(window)
    start_meeting(window)
    meeting = window.meeting
    old = meeting._generation
    end_and_wait(window)
    start_meeting(window)
    assert meeting._generation != old
    say(meeting.controller, USER, 20)
    assert wait_until(lambda: view_lines(window) == ["You: Guten Tag"])
    shown, state = view_lines(window), label(window)
    contribution = uuid4()
    line = MeetingLine(contribution, TABLE, "Zu spät", datetime(2026, 11, 17, 9, 0, tzinfo=UTC))
    for event in (
        MeetingEvent(Kind.PENDING, TABLE, contribution_id=uuid4()),
        MeetingEvent(Kind.LINE, TABLE, contribution_id=contribution, line=line),
        MeetingEvent(Kind.STOPPED),
    ):
        meeting.meeting_event.emit(replace(event, generation=old))
    assert view_lines(window) == shown and label(window) == state == "Meeting running"
    assert meeting.controller is not None and meeting.controller.running
    assert window.session_owner.state is SessionState.RUNNING
    end_and_wait(window)
