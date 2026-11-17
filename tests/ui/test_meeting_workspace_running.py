"""The running meeting: running text view and status strip (CAP-0177 WI-05).

Offscreen UI tests over the real ``MeetingController`` on synthetic adapters
(``_meeting_window.py``): contributions are fed into the inputs' segmenters (``say``) and the
events reach the page through the queued hand-off, as on the capture and worker threads. The
Integration halves of AC-04, AC-08, AC-09 and AC-24 are in ``tests/meeting/test_controller*.py``
and the Unit halves of AC-08, AC-09 and AC-14 in ``test_language_gate.py`` and
``test_turn_queue.py``.
"""

from __future__ import annotations

import os
import threading

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tests._spy_window import spies  # noqa: F401
from tests.meeting.support import pause, say
from tests.ui._meeting_window import (
    TABLE,
    USER,
    assign_table,
    meeting_window,  # noqa: F401
    start_meeting,
)
from tests.ui.test_main_window_session import wait_until


def view_text(window) -> str:
    return window.meeting.running_view.text.toPlainText()


def view_lines(window) -> list[str]:
    text = view_text(window)
    return text.split("\n") if text else []


def state(window, role) -> str:
    return window.meeting.input_states[role].text()


def running(window):
    assign_table(window)
    start_meeting(window)
    return window.meeting.controller


def translated(window, count: int) -> bool:
    controller = window.meeting.controller
    return controller is not None and len(controller.results) >= count


# AC-04 / AC-20 -----------------------------------------------------------------------------


def test_ac04_a_mandarin_table_contribution_becomes_a_german_table_line(window) -> None:
    meeting = window.meeting
    assert meeting.running_view.text.placeholderText() == ""  # no meeting yet
    controller = running(window)
    assert meeting.running_view.text.placeholderText() == "Listening — nothing said yet"
    assert view_lines(window) == []
    hold = threading.Event()
    window.meeting_factory.recognizer.hold = hold
    say(controller, TABLE, 10)
    assert wait_until(lambda: view_lines(window) == ["Table: Translating…"])
    hold.set()
    assert wait_until(lambda: view_lines(window) == ["Table: Hallo, willkommen"])


def test_ac20_both_sides_interleave_by_speech_end_in_german_only(window) -> None:
    controller = running(window)
    contributions = ((TABLE, 10), (USER, 20), (TABLE, 11), (USER, 21), (TABLE, 12))
    for count, (role, tag) in enumerate(contributions, start=1):
        say(controller, role, tag)
        assert wait_until(lambda count=count: translated(window, count))
        if role is USER:  # Mandarin played on the table speaker: wait out the guard tail
            wait_until(lambda: False, window.config.meeting.guard_tail_ms + 100)
    expected = [
        "Table: Hallo, willkommen",
        "You: Guten Tag",
        "Table: Danke",
        "You: Wir beginnen",
        "Table: Auf Wiedersehen",
    ]
    assert wait_until(lambda: view_lines(window) == expected), view_lines(window)
    ended = [result.captured_at for result in controller.results]
    assert ended == sorted(ended)
    text = view_text(window)
    assert not any("一" <= char <= "鿿" for char in text)  # no table-language text


def test_ac20_uia_the_running_view_and_the_strip_are_named(window) -> None:
    from PySide6.QtGui import QAccessible
    from PySide6.QtWidgets import QProgressBar

    meeting = window.meeting
    running(window)
    view = QAccessible.queryAccessibleInterface(meeting.running_view.text)
    assert view.text(QAccessible.Text.Name) == "Meeting text"
    bars = meeting.running_box.findChildren(QProgressBar)
    names = [QAccessible.queryAccessibleInterface(bar).text(QAccessible.Text.Name) for bar in bars]
    assert names == ["Table microphone", "Your microphone"]
    for label in meeting.input_states.values():
        name = QAccessible.queryAccessibleInterface(label).text(QAccessible.Text.Name)
        assert name == "Listening"
    # Keyboard order: … Start → running view → End (spec §2.3 "Accessibility").
    assert next_tab_stop(meeting.start_button) is meeting.running_view.text
    assert next_tab_stop(meeting.running_view.text) is meeting.end_button


def next_tab_stop(widget):
    from PySide6.QtCore import Qt

    candidate = widget.nextInFocusChain()
    while not candidate.focusPolicy() & Qt.FocusPolicy.TabFocus or not candidate.isVisible():
        candidate = candidate.nextInFocusChain()
    return candidate


def test_the_view_follows_the_newest_line_unless_the_po_scrolled_up(window) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    controller = running(window)
    panel = window.meeting.running_view
    for tag in range(50, 90):
        say(controller, TABLE, tag)
    assert wait_until(lambda: translated(window, 40))
    assert wait_until(lambda: "Translating…" not in view_text(window))
    bar = panel.text.verticalScrollBar()
    assert bar.maximum() > 0 and bar.value() == bar.maximum()
    QTest.keyClick(panel.text, Qt.Key.Key_Home)  # the PO scrolls up
    assert not panel.follow and bar.value() == 0
    say(controller, USER, 20)
    assert wait_until(lambda: translated(window, 41))
    assert wait_until(lambda: view_lines(window)[-1] == "You: Guten Tag")
    assert bar.value() == 0  # the view stays where the PO left it
    QTest.keyClick(panel.text, Qt.Key.Key_End)
    assert panel.follow


# AC-08 / AC-09 -----------------------------------------------------------------------------


def test_ac08_german_into_the_table_input_is_counted_not_shown(window) -> None:
    controller = running(window)
    ignored = window.meeting.ignored_labels
    assert ignored[TABLE].isHidden() and ignored[USER].isHidden()
    say(controller, TABLE, 30)
    assert wait_until(
        lambda: ignored[TABLE].text() == "1 contribution(s) in another language ignored"
    )
    assert not ignored[TABLE].isHidden() and ignored[USER].isHidden()
    assert view_lines(window) == []  # the placeholder was withdrawn; no text kept
    say(controller, TABLE, 30)
    assert wait_until(lambda: ignored[TABLE].text().startswith("2 "))
    assert "Deutsch" not in view_text(window) and controller.results == ()


def test_ac09_mandarin_into_your_microphone_is_counted_not_shown(window) -> None:
    controller = running(window)
    ignored = window.meeting.ignored_labels
    say(controller, USER, 40)
    assert wait_until(
        lambda: ignored[USER].text() == "1 contribution(s) in another language ignored"
    )
    assert ignored[TABLE].isHidden()
    assert view_lines(window) == [] and controller.results == ()


# AC-14 -------------------------------------------------------------------------------------


def test_ac14_the_falling_behind_notice_shows_above_the_soft_limit_until_caught_up(window) -> None:
    controller = running(window)
    behind = window.meeting.behind_label
    assert behind.isHidden()
    hold = threading.Event()
    window.meeting_factory.recognizer.hold = hold
    for tag in range(50, 58):  # one in flight, seven queued: above the limit of six
        say(controller, TABLE, tag)
    assert wait_until(lambda: not behind.isHidden())
    assert behind.text() == "Translation is falling behind — nothing is lost"
    hold.set()
    assert wait_until(lambda: translated(window, 8))  # nothing dropped
    assert wait_until(behind.isHidden)
    assert wait_until(
        lambda: len(view_lines(window)) == 8 and "Translating…" not in view_text(window)
    )


# AC-24 -------------------------------------------------------------------------------------


def test_ac24_both_inputs_show_muted_while_mandarin_plays_then_listening(window) -> None:
    from PySide6.QtTest import QTest

    controller = running(window)
    assert wait_until(lambda: state(window, TABLE) == "Listening" == state(window, USER))
    renders = window.meeting_factory.renders
    renders.gate = threading.Event()
    say(controller, USER, 20)
    muted = "Muted while speaking Mandarin (Simplified)"
    assert wait_until(lambda: state(window, TABLE) == muted == state(window, USER))
    say(controller, TABLE, 10)  # muted: forms no contribution
    renders.gate.set()
    assert wait_until(lambda: translated(window, 1))
    QTest.qWait(window.config.meeting.guard_tail_ms + 100)  # the guard tail has passed
    for role in (TABLE, USER):
        for block in pause(1):
            controller.captures[role].process_block(block)
    assert wait_until(lambda: state(window, TABLE) == "Listening" == state(window, USER))
    assert view_lines(window) == ["You: Guten Tag"]


def test_the_level_bars_follow_each_input_and_reset_after_the_meeting(window) -> None:
    from tests.ui._meeting_window import end_and_wait

    controller = running(window)
    bars = window.meeting.level_bars
    threading.Thread(target=controller.captures[TABLE].on_level, args=(0.5,)).start()
    assert wait_until(lambda: bars[TABLE].value() == 50)
    assert bars[USER].value() == 0
    end_and_wait(window)
    assert bars[TABLE].value() == 0
    assert state(window, TABLE) == "" == state(window, USER)
