"""The running view's order, late events and the GUI-thread rule (CAP-0177 WI-05 review).

The page gets ``MeetingEvent``s as the controller publishes them (``meeting_event``); these
tests drive that hand-off directly to pin the order of the running view (AC-20, spec §2.3
"newest at the bottom"), that events after ``STOPPED`` are ignored, and that levels from a
capture thread reach the widgets on the GUI thread only.
"""

from __future__ import annotations

import os
import threading
from datetime import UTC, datetime, timedelta
from uuid import uuid4

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from lianiq.meeting.events import MeetingEvent, MeetingEventKind, MeetingLine
from tests._spy_window import spies  # noqa: F401
from tests.ui._meeting_window import (
    TABLE,
    USER,
    assign_table,
    end_and_wait,
    meeting_window,  # noqa: F401
    start_meeting,
)
from tests.ui.test_main_window_session import wait_until

T0 = datetime(2026, 11, 17, 10, 0, tzinfo=UTC)
Kind = MeetingEventKind


def view_lines(window) -> list[str]:
    text = window.meeting.running_view.text.toPlainText()
    return text.split("\n") if text else []


def running(window):
    assign_table(window)
    start_meeting(window)
    return window.meeting


def pending(meeting, contribution_id) -> None:
    meeting.meeting_event.emit(MeetingEvent(Kind.PENDING, TABLE, contribution_id=contribution_id))


def line(meeting, contribution_id, role, text: str, seconds: float) -> None:
    item = MeetingLine(contribution_id, role, text, T0 + timedelta(seconds=seconds))
    meeting.meeting_event.emit(
        MeetingEvent(Kind.LINE, role, contribution_id=contribution_id, line=item)
    )


def test_ac20_placeholders_stay_below_the_lines_in_arrival_order(window) -> None:
    meeting = running(window)
    first, second = uuid4(), uuid4()
    line(meeting, uuid4(), USER, "Guten Tag", 1)
    pending(meeting, first)
    pending(meeting, second)
    assert view_lines(window) == ["You: Guten Tag", "Table: Translating…", "Table: Translating…"]
    line(meeting, first, TABLE, "Erste", 2)
    assert view_lines(window) == ["You: Guten Tag", "Table: Erste", "Table: Translating…"]
    line(meeting, second, TABLE, "Zweite", 3)
    assert view_lines(window) == ["You: Guten Tag", "Table: Erste", "Table: Zweite"]


def test_ac20_lines_are_ordered_by_speech_end_not_by_arrival(window) -> None:
    meeting = running(window)
    line(meeting, uuid4(), TABLE, "Später", 5)
    line(meeting, uuid4(), USER, "Früher", 2)
    pending(meeting, uuid4())
    line(meeting, uuid4(), TABLE, "Mitte", 3)
    assert view_lines(window) == [
        "You: Früher",
        "Table: Mitte",
        "Table: Später",
        "Table: Translating…",
    ]


def test_events_after_the_meeting_ended_are_ignored(window) -> None:
    meeting = running(window)
    line(meeting, uuid4(), USER, "Guten Tag", 1)
    end_and_wait(window)
    shown = view_lines(window)
    line(meeting, uuid4(), TABLE, "Zu spät", 2)
    pending(meeting, uuid4())
    meeting.meeting_event.emit(MeetingEvent(Kind.IGNORED, TABLE, count=3))
    meeting.meeting_event.emit(MeetingEvent(Kind.LISTENING, TABLE))
    assert view_lines(window) == shown == ["You: Guten Tag"]
    assert meeting.ignored_labels[TABLE].isHidden()
    assert meeting.input_states[TABLE].text() == ""


def test_levels_from_a_capture_thread_reach_the_bar_on_the_gui_thread(window) -> None:
    meeting = running(window)
    bar, threads = meeting.level_bars[TABLE], []
    set_value = bar.setValue

    def recording_set_value(value) -> None:
        threads.append(threading.current_thread())
        set_value(value)

    bar.setValue = recording_set_value
    capture = meeting.controller.captures[TABLE]
    worker = threading.Thread(target=capture.on_level, args=(0.4,))
    worker.start()
    worker.join()
    assert wait_until(lambda: bar.value() == 40)
    assert threads and all(t is threading.main_thread() for t in threads)
