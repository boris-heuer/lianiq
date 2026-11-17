"""Cross-device feedback guard with an injected clock (CAP-0177 contract §4).

Unit halves of AC-24 (Mandarin output on the table speaker mutes both inputs in ``mute``),
AC-26 (German speech on a speaker mutes both inputs, on a headset neither) and AC-12
(playback waits for a muted, speaking capture up to ``meeting.max_playback_defer_ms``, then
closes it; with ``open`` Mandarin output never waits for the table input). The clock is a
float in seconds, so each boundary is checked 1 ms before and after, never exactly on it.
"""

from __future__ import annotations

import pytest

from lianiq.meeting.contracts import MeetingRole, TableInputDuringOutput
from lianiq.meeting.feedback_guard import FeedbackGuard, PlaybackDecision
from tests.meeting.support import FakeClock

TABLE = MeetingRole.TABLE_CAPTURE
USER = MeetingRole.USER_CAPTURE
TABLE_RENDER = MeetingRole.TABLE_RENDER
LOCAL_RENDER = MeetingRole.LOCAL_RENDER
MUTE = TableInputDuringOutput.MUTE
OPEN = TableInputDuringOutput.OPEN
NOBODY: frozenset[MeetingRole] = frozenset()
TAIL_MS = 300
DEFER_MS = 5000


def guard(
    option: TableInputDuringOutput = MUTE,
    headset: bool = False,
    clock: FakeClock | None = None,
    tail_ms: int = TAIL_MS,
) -> FeedbackGuard:
    return FeedbackGuard(
        table_input_during_output=option,
        local_render_is_headset=headset,
        guard_tail_ms=tail_ms,
        max_playback_defer_ms=DEFER_MS,
        clock=clock or FakeClock(),
    )


def test_decision_values_are_the_contract_values():
    assert [decision.value for decision in PlaybackDecision] == [
        "play",
        "wait",
        "close_and_play",
    ]


@pytest.mark.parametrize(
    ("option", "headset", "target", "muted"),
    [
        (MUTE, False, TABLE_RENDER, {USER, TABLE}),
        (MUTE, True, TABLE_RENDER, {USER, TABLE}),
        (OPEN, False, TABLE_RENDER, {USER}),
        (OPEN, True, TABLE_RENDER, {USER}),
        (MUTE, False, LOCAL_RENDER, {USER, TABLE}),
        (OPEN, False, LOCAL_RENDER, {USER, TABLE}),
        (MUTE, True, LOCAL_RENDER, set()),
        (OPEN, True, LOCAL_RENDER, set()),
    ],
)
def test_muted_by_is_the_contract_table(option, headset, target, muted):
    assert guard(option, headset).muted_by(target) == frozenset(muted)


@pytest.mark.parametrize("target", [TABLE, USER])
def test_muted_by_rejects_capture_roles(target):
    with pytest.raises(ValueError):
        guard().muted_by(target)


@pytest.mark.parametrize("role", [TABLE_RENDER, LOCAL_RENDER])
def test_is_muted_rejects_render_roles(role):
    with pytest.raises(ValueError):
        guard().is_muted(role)


def test_nothing_is_muted_without_playback():
    subject = guard()
    assert not subject.is_muted(TABLE)
    assert not subject.is_muted(USER)


def test_ac24_mandarin_output_mutes_both_inputs_until_end_plus_guard_tail():
    clock = FakeClock()
    subject = guard(MUTE, clock=clock)
    subject.playback_started(TABLE_RENDER)
    assert subject.is_muted(TABLE) and subject.is_muted(USER)
    clock.advance_ms(4000)  # a long playback stays muted throughout
    assert subject.is_muted(TABLE) and subject.is_muted(USER)
    subject.playback_ended(TABLE_RENDER)
    clock.advance_ms(TAIL_MS - 1)
    assert subject.is_muted(TABLE) and subject.is_muted(USER)
    clock.advance_ms(2)
    assert not subject.is_muted(TABLE) and not subject.is_muted(USER)


def test_open_mode_keeps_the_table_input_open_during_mandarin_output():
    clock = FakeClock()
    subject = guard(OPEN, clock=clock)
    subject.playback_started(TABLE_RENDER)
    assert subject.is_muted(USER)
    assert not subject.is_muted(TABLE)
    subject.playback_ended(TABLE_RENDER)
    assert subject.is_muted(USER)
    assert not subject.is_muted(TABLE)
    clock.advance_ms(TAIL_MS + 1)
    assert not subject.is_muted(USER)


@pytest.mark.parametrize("option", [MUTE, OPEN])
def test_ac26_german_speech_on_a_speaker_mutes_both_inputs_until_the_tail_ends(option):
    clock = FakeClock()
    subject = guard(option, headset=False, clock=clock)
    subject.playback_started(LOCAL_RENDER)
    assert subject.is_muted(TABLE) and subject.is_muted(USER)
    subject.playback_ended(LOCAL_RENDER)
    clock.advance_ms(TAIL_MS - 1)
    assert subject.is_muted(TABLE) and subject.is_muted(USER)
    clock.advance_ms(2)
    assert not subject.is_muted(TABLE) and not subject.is_muted(USER)


@pytest.mark.parametrize("option", [MUTE, OPEN])
def test_ac26_german_speech_on_a_headset_mutes_neither_input(option):
    subject = guard(option, headset=True)
    subject.playback_started(LOCAL_RENDER)
    assert not subject.is_muted(TABLE) and not subject.is_muted(USER)
    subject.playback_ended(LOCAL_RENDER)
    assert not subject.is_muted(TABLE) and not subject.is_muted(USER)


def test_zero_guard_tail_unmutes_at_playback_end():
    subject = guard(MUTE, tail_ms=0)
    subject.playback_started(TABLE_RENDER)
    subject.playback_ended(TABLE_RENDER)
    assert not subject.is_muted(TABLE) and not subject.is_muted(USER)


def test_tail_of_one_target_does_not_end_while_the_other_plays():
    clock = FakeClock()
    subject = guard(OPEN, headset=False, clock=clock)
    subject.playback_started(LOCAL_RENDER)  # mutes both
    subject.playback_ended(LOCAL_RENDER)
    subject.playback_started(TABLE_RENDER)  # mutes the user input only
    clock.advance_ms(TAIL_MS + 1)
    assert not subject.is_muted(TABLE)
    assert subject.is_muted(USER)


def test_playback_plays_when_no_muted_capture_is_speaking():
    clock = FakeClock()
    subject = guard(MUTE, clock=clock)
    assert subject.before_playback(TABLE_RENDER, NOBODY, clock()) is PlaybackDecision.PLAY


@pytest.mark.parametrize("speaking", [{TABLE}, {USER}, {TABLE, USER}])
def test_ac12_playback_waits_for_a_speaking_muted_capture_then_closes_it(speaking):
    clock = FakeClock()
    subject = guard(MUTE, clock=clock)
    since = clock()
    roles = frozenset(speaking)
    assert subject.before_playback(TABLE_RENDER, roles, since) is PlaybackDecision.WAIT
    clock.advance_ms(DEFER_MS - 1)
    assert subject.before_playback(TABLE_RENDER, roles, since) is PlaybackDecision.WAIT
    clock.advance_ms(2)
    assert subject.before_playback(TABLE_RENDER, roles, since) is PlaybackDecision.CLOSE_AND_PLAY


def test_ac12_playback_plays_once_the_speaking_capture_is_idle():
    clock = FakeClock()
    subject = guard(MUTE, clock=clock)
    since = clock()
    assert subject.before_playback(TABLE_RENDER, frozenset({USER}), since) is PlaybackDecision.WAIT
    clock.advance_ms(1200)
    assert subject.before_playback(TABLE_RENDER, NOBODY, since) is PlaybackDecision.PLAY


def test_ac12_open_mode_mandarin_output_does_not_wait_for_the_table_input():
    clock = FakeClock()
    subject = guard(OPEN, clock=clock)
    since = clock()
    assert subject.before_playback(TABLE_RENDER, frozenset({TABLE}), since) is PlaybackDecision.PLAY
    assert (
        subject.before_playback(TABLE_RENDER, frozenset({TABLE, USER}), since)
        is PlaybackDecision.WAIT
    )


def test_headset_german_speech_never_waits():
    clock = FakeClock()
    subject = guard(MUTE, headset=True, clock=clock)
    both = frozenset({TABLE, USER})
    assert subject.before_playback(LOCAL_RENDER, both, clock()) is PlaybackDecision.PLAY


def test_waiting_is_measured_from_waiting_since():
    clock = FakeClock()
    subject = guard(MUTE, clock=clock)
    clock.advance_ms(DEFER_MS * 3)
    since = clock() - (DEFER_MS - 10) / 1000.0
    speaking = frozenset({TABLE})
    assert subject.before_playback(TABLE_RENDER, speaking, since) is PlaybackDecision.WAIT
    clock.advance_ms(20)
    assert subject.before_playback(TABLE_RENDER, speaking, since) is PlaybackDecision.CLOSE_AND_PLAY


@pytest.mark.parametrize(
    ("tail_ms", "defer_ms"),
    [(-1, DEFER_MS), (TAIL_MS, -1)],
    ids=["negative tail", "negative deferral"],
)
def test_durations_must_not_be_negative(tail_ms, defer_ms):
    with pytest.raises(ValueError):
        FeedbackGuard(MUTE, False, tail_ms, defer_ms, FakeClock())
