"""The running meeting: local-language speech and device loss (CAP-0177 WI-05).

Offscreen UI tests over the real ``MeetingController`` on synthetic adapters
(``_meeting_window.py``). The Integration halves of AC-05 and AC-15 are in
``tests/meeting/test_controller.py`` and ``test_controller_endpoints.py``; the idle halves of
the speech switch (AC-28) are in ``test_meeting_workspace.py``.
"""

from __future__ import annotations

import os
import threading

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from lianiq.ui.notices import Severity
from tests._spy_window import spies  # noqa: F401
from tests.meeting.support import DE, ZH, Played, say
from tests.ui._meeting_window import (
    HEADSET,
    JABRA_MIC,
    JABRA_SPEAKER,
    LOCAL,
    MEETING,
    SPEAKER,
    TABLE,
    USER,
    assign_table,
    choose,
    meeting_window,  # noqa: F401
    start_meeting,
)
from tests.ui.test_main_window_session import wait_until


def toggle(checkbox) -> None:
    """A click on the box itself (the checkbox spans the row; its label ends earlier)."""
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    QTest.mouseClick(checkbox, Qt.MouseButton.LeftButton, pos=QPoint(6, checkbox.height() // 2))


def lines(window) -> list[str]:
    text = window.meeting.running_view.text.toPlainText()
    return text.split("\n") if text else []


def results(window) -> int:
    controller = window.meeting.controller
    return 0 if controller is None else len(controller.results)


# AC-05 -------------------------------------------------------------------------------------


def test_ac05_speak_german_can_be_switched_while_the_meeting_runs(window) -> None:
    meeting, renders = window.meeting, window.meeting_factory.renders
    assign_table(window)
    choose(window, LOCAL, HEADSET)
    switch = meeting.speak_local_checkbox
    assert switch.isEnabled() and not switch.isChecked()
    start_meeting(window)
    assert switch.isEnabled()  # it can change during the meeting
    controller = meeting.controller
    say(controller, TABLE, 10)
    assert wait_until(lambda: results(window) == 1)
    assert renders.played == []  # off: no German speech
    toggle(switch)
    assert switch.isChecked() and window.config.meeting.speak_local
    assert meeting.controller is controller  # switching it on never stops the meeting
    say(controller, TABLE, 11)
    assert wait_until(lambda: results(window) == 2)
    assert wait_until(lambda: renders.played == [Played(HEADSET.runtime_index, DE)])
    shown = ["Table: Hallo, willkommen", "Table: Danke"]
    assert wait_until(lambda: lines(window) == shown)  # the text is still shown
    toggle(switch)  # off again
    wait_until(lambda: False, window.config.meeting.guard_tail_ms + 100)  # speaker: tail
    say(controller, TABLE, 12)
    say(controller, USER, 20)
    assert wait_until(lambda: results(window) == 4)
    assert renders.played[1:] == [Played(JABRA_SPEAKER.runtime_index, ZH)]


@pytest.mark.parametrize("output", [None, JABRA_SPEAKER])
def test_ac05_while_running_the_switch_stays_disabled_and_names_why(window, output) -> None:
    meeting = window.meeting
    assign_table(window)
    choose(window, LOCAL, output)
    start_meeting(window)
    switch = meeting.speak_local_checkbox
    assert not switch.isEnabled() and not switch.isChecked()
    reason = (
        "German speech cannot use the table speaker"
        if output is not None
        else "Not available: missing output for German speech"
    )
    assert switch.toolTip() == reason == switch.accessibleDescription()


# AC-15 -------------------------------------------------------------------------------------


def test_ac15_a_lost_table_speakerphone_is_named_and_the_po_input_keeps_listening(
    window,
) -> None:
    meeting = window.meeting
    assign_table(window)
    start_meeting(window)
    controller = meeting.controller
    hold = threading.Event()
    window.meeting_factory.recognizer.hold = hold
    say(controller, TABLE, 10)  # queued before the loss: it still finishes
    window.fake_devices.unplug(JABRA_MIC)
    window.fake_devices.unplug(JABRA_SPEAKER)
    window.device_setup.monitor_tick()
    assert meeting.input_states[TABLE].text() == "Device lost"
    assert meeting.input_states[USER].text() == "Listening"
    assert meeting.level_bars[TABLE].value() == 0
    notices = {n.key: n for n in window.notices.live(MEETING)}
    microphone = notices["meeting.table_capture-lost"]
    speaker = notices["meeting.table_render-lost"]
    assert microphone.severity is Severity.BLOCKING is speaker.severity  # persistent
    assert "Microphone (Jabra Speak2 75)" in microphone.title
    assert "Speakers (Jabra Speak2 75)" in speaker.title
    assert microphone.source == "Meeting · Table microphone"
    assert speaker.source == "Meeting · Table speaker"
    assert controller.lost_roles == {TABLE, SPEAKER}
    hold.set()
    assert wait_until(lambda: results(window) == 1)  # the queued contribution finished
    say(controller, USER, 20)  # the PO input still listens
    assert wait_until(lambda: results(window) == 2)
    assert window.meeting_factory.renders.played == []  # no other device is used
    window.device_setup.monitor_tick()  # reported once
    assert len([n for n in window.notices.history() if n.key.endswith("-lost")]) == 2
    assert wait_until(lambda: lines(window) == ["Table: Hallo, willkommen", "You: Guten Tag"])


def test_ac15_the_loss_notices_are_resolved_by_the_next_start(window) -> None:
    from tests.ui._meeting_window import end_and_wait

    assign_table(window)
    start_meeting(window)
    window.fake_devices.unplug(HEADSET)  # assigned to nothing: no notice
    window.fake_devices.unplug(JABRA_SPEAKER)
    window.device_setup.monitor_tick()
    assert [n.key for n in window.notices.live(MEETING)] == ["meeting.table_render-lost"]
    end_and_wait(window)
    assert window.notices.get("meeting.table_render-lost") is not None  # persistent
    window.fake_devices.set(*window.fake_devices.endpoints)  # replugged
    # No monitor runs while idle: list them, don't race the stop's refresh.
    assert window.device_setup.refresh()
    assert window.meeting.start_button.isEnabled()
    start_meeting(window)
    assert window.notices.get("meeting.table_render-lost") is None
    assert window.meeting.input_states[TABLE].text() == "Listening"


def test_ac15_a_lost_input_shows_no_level_while_the_other_does(window) -> None:
    assign_table(window)
    start_meeting(window)
    meeting = window.meeting
    window.fake_devices.unplug(JABRA_MIC)
    window.device_setup.monitor_tick()
    captures, bars = meeting.controller.captures, meeting.level_bars
    for role, level in ((TABLE, 0.7), (USER, 0.3)):
        worker = threading.Thread(target=captures[role].on_level, args=(level,))
        worker.start()
        worker.join()
    assert wait_until(lambda: bars[USER].value() == 30)
    assert bars[TABLE].value() == 0 and meeting.input_states[TABLE].text() == "Device lost"


def test_ac15_one_device_in_two_roles_gives_one_loss_notice(window) -> None:
    assign_table(window)
    choose(window, LOCAL, JABRA_SPEAKER)  # German output = table speaker (switch disabled)
    start_meeting(window)
    window.fake_devices.unplug(JABRA_SPEAKER)
    window.device_setup.monitor_tick()
    assert [n.key for n in window.notices.live(MEETING)] == ["meeting.table_render-lost"]


def test_ac05_a_refused_switch_is_reverted_and_names_the_reason(window) -> None:
    meeting = window.meeting
    assign_table(window)
    choose(window, LOCAL, HEADSET)
    start_meeting(window)

    def refuse(_on) -> None:
        raise ValueError("no output")

    meeting.controller.set_speak_local = refuse
    switch = meeting.speak_local_checkbox
    toggle(switch)
    assert not switch.isChecked() and not window.config.meeting.speak_local
    assert switch.toolTip() == "German speech cannot use the table speaker"
    assert meeting.controller is not None  # the meeting keeps running
