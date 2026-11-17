"""Meeting controller feedback guard on synthetic adapters (CAP-0177 WI-03, contract §4).

Integration halves of AC-11, AC-12, AC-24 and AC-26: what a capture forms while an output
plays on a render endpoint, and how a ready output waits for a running contribution.
"""

from __future__ import annotations

import time

import pytest

from lianiq.meeting import MeetingRole, TableInputDuringOutput
from lianiq.meeting.controller import MeetingEventKind as Kind
from tests.meeting.conftest import meeting_endpoints
from tests.meeting.support import (
    DE,
    LOCAL_OUTPUT,
    TABLE_SPEAKER,
    ZH,
    Line,
    Played,
    feed,
    pause,
    say,
    speech,
    wait_until,
)

TABLE, USER = MeetingRole.TABLE_CAPTURE, MeetingRole.USER_CAPTURE
SCRIPT = {
    10: Line(ZH, "请讲"),
    20: Line(DE, "Guten Tag"),
    21: Line(DE, "Nach dem Schutz"),
    30: Line(DE, "Echo"),
    31: Line(ZH, "回声"),
    40: Line(ZH, "我还在说"),
}


def detected(harness) -> list[int]:
    return [tag for tag, language in harness.recognizer.calls if language is None]


def speak_during_playback(harness, *roles_and_tags) -> None:
    def during(_index) -> None:  # only during the first playback
        harness.renders.during = None
        for role, tag in roles_and_tags:
            say(harness.controller, role, tag)

    harness.renders.during = during


def test_ac11_ac24_no_contribution_during_table_speech_until_end_plus_guard_tail(meeting) -> None:
    """AC-11 / AC-24 (Integration, ``mute``): both inputs form nothing until end + tail."""
    harness = meeting(SCRIPT, guard_tail_ms=300)
    controller = harness.controller
    speak_during_playback(harness, (USER, 30), (TABLE, 31))
    controller.start()
    say(controller, USER, 20)
    assert wait_until(lambda: len(controller.results) == 1)
    assert harness.renders.played == [Played(TABLE_SPEAKER, ZH)]

    harness.clock.advance_ms(299)  # still inside the guard tail
    say(controller, USER, 30)
    say(controller, TABLE, 31)
    harness.clock.advance_ms(2)
    feed(controller, TABLE, pause(1))
    say(controller, USER, 21)
    assert wait_until(lambda: len(controller.results) == 2)
    assert detected(harness) == [20, 21]
    muted = [(event.role, event.language) for event in harness.events.of(Kind.MUTED)]
    assert muted[:2] == [(TABLE, ZH), (USER, ZH)]  # "Muted while speaking {table language}"
    assert {event.role for event in harness.events.of(Kind.UNMUTED)} == {TABLE, USER}


def test_ac24_open_keeps_the_table_input_open_during_table_speech(meeting) -> None:
    """``open``: only the PO microphone is muted while table-language speech plays."""
    harness = meeting(SCRIPT, mode=TableInputDuringOutput.OPEN)
    speak_during_playback(harness, (USER, 30), (TABLE, 31))
    harness.controller.start()
    say(harness.controller, USER, 20)
    assert wait_until(lambda: len(harness.controller.results) == 2)
    assert detected(harness) == [20, 31]
    assert [event.role for event in harness.events.of(Kind.MUTED)] == [USER]


def test_ac12_output_waits_until_the_running_table_contribution_ends(meeting) -> None:
    """AC-12 (Integration): a ready output waits while a capture it will mute is speaking."""
    harness = meeting(SCRIPT)
    controller = harness.controller
    controller.start()
    feed(controller, TABLE, speech(40))  # mid-contribution, no pause yet
    say(controller, USER, 20)
    assert wait_until(lambda: harness.synthesizer.calls)
    time.sleep(0.2)
    assert harness.renders.played == []  # waiting for the table segmenter
    feed(controller, TABLE, pause())  # the contribution ends: idle → the output plays
    assert wait_until(lambda: len(controller.results) == 2)
    assert harness.renders.played == [Played(TABLE_SPEAKER, ZH)]
    assert detected(harness) == [20, 40]


def test_ac12_after_the_maximum_deferral_the_contribution_is_closed_and_processed(
    meeting,
) -> None:
    """AC-12: speech past ``max_playback_defer_ms`` is closed, processed, then the output plays."""
    harness = meeting(SCRIPT, max_playback_defer_ms=5_000)
    controller = harness.controller
    controller.start()
    feed(controller, TABLE, speech(40))
    say(controller, USER, 20)
    assert wait_until(lambda: harness.synthesizer.calls)
    harness.clock.advance_ms(4_999)
    time.sleep(0.1)
    assert harness.renders.played == []
    harness.clock.advance_ms(2)
    assert wait_until(lambda: harness.renders.played == [Played(TABLE_SPEAKER, ZH)])
    assert wait_until(lambda: len(controller.results) == 2)  # closed, processed, not dropped
    assert detected(harness) == [20, 40]
    assert not controller.captures[TABLE].speaking


def test_ac12_with_open_table_speech_does_not_wait_for_the_table_segmenter(meeting) -> None:
    """AC-12: with ``open`` table-language output does not wait for the table input."""
    harness = meeting(SCRIPT, mode=TableInputDuringOutput.OPEN)
    controller = harness.controller
    controller.start()
    feed(controller, TABLE, speech(40))
    say(controller, USER, 20)
    assert wait_until(lambda: harness.renders.played == [Played(TABLE_SPEAKER, ZH)])
    assert controller.captures[TABLE].speaking  # the table contribution keeps running


@pytest.mark.parametrize("headset", [False, True])
def test_ac26_local_speech_on_a_speaker_mutes_both_inputs_but_not_on_a_headset(
    meeting, headset
) -> None:
    """AC-26 (Integration): local-language speech on a speaker mutes both inputs + tail."""
    harness = meeting(SCRIPT, speak_local=True, endpoints=meeting_endpoints(headset=headset))
    controller = harness.controller
    speak_during_playback(harness, (TABLE, 31), (USER, 30))
    controller.start()
    say(controller, TABLE, 10)
    assert wait_until(lambda: len(controller.results) == (3 if headset else 1))
    assert harness.renders.played[0] == Played(LOCAL_OUTPUT, DE)
    harness.clock.advance_ms(100)  # inside the 300 ms tail
    say(controller, USER, 30)
    time.sleep(0.1)
    if headset:
        assert detected(harness)[:3] == [10, 31, 30]
        local = [e for e in harness.events.of(Kind.MUTED) if e.language == DE]
        assert local == []  # only the PO's table-language speech muted anything
    else:
        assert detected(harness) == [10]
        muted = [(event.role, event.language) for event in harness.events.of(Kind.MUTED)]
        assert muted == [(TABLE, DE), (USER, DE)]  # "Muted while speaking {local language}"
