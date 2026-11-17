"""No-drop turn queue across both inputs (CAP-0177 contract §3).

Unit half of AC-14: beyond the soft limit nothing is dropped and ``falling_behind`` holds
until the queue is back at or below the limit.
"""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import numpy as np
import pytest

from lianiq.domain import AudioUtterance
from lianiq.meeting.contracts import MeetingRole
from lianiq.meeting.turn_queue import TURN_QUEUE_SOFT_LIMIT, Contribution, TurnQueue
from tests.meeting.support import DE, ZH

T0 = datetime(2026, 11, 16, 10, 0, tzinfo=UTC)
SILENCE = AudioUtterance(samples=np.zeros(160, dtype=np.float32), sample_rate=16_000)


def contribution(offset_ms: int, role: MeetingRole = MeetingRole.TABLE_CAPTURE) -> Contribution:
    source, target = (ZH, DE) if role is MeetingRole.TABLE_CAPTURE else (DE, ZH)
    return Contribution(
        contribution_id=uuid4(),
        role=role,
        source_language=source,
        target_language=target,
        ended_at=T0 + timedelta(milliseconds=offset_ms),
        utterance=SILENCE,
    )


def drain(queue: TurnQueue) -> list[Contribution]:
    items = []
    while (item := queue.take(timeout=0)) is not None:
        items.append(item)
    return items


def test_soft_limit_is_six():
    assert TURN_QUEUE_SOFT_LIMIT == 6


def test_empty_queue_take_times_out_with_none():
    queue = TurnQueue()
    assert len(queue) == 0
    assert queue.take(timeout=0) is None
    started = time.monotonic()
    assert queue.take(timeout=0.05) is None
    assert time.monotonic() - started >= 0.04


def test_items_come_out_sorted_by_speech_end_across_both_inputs():
    queue = TurnQueue()
    late_table = contribution(300)
    early_user = contribution(100, MeetingRole.USER_CAPTURE)
    middle_table = contribution(200)
    for item in (late_table, early_user, middle_table):
        queue.put(item)
    assert drain(queue) == [early_user, middle_table, late_table]


def test_equal_speech_end_keeps_insertion_order():
    queue = TurnQueue()
    first = contribution(100)
    second = contribution(100, MeetingRole.USER_CAPTURE)
    queue.put(first)
    queue.put(second)
    assert drain(queue) == [first, second]


def test_ac14_queue_never_drops_and_reports_falling_behind_only_above_the_limit():
    queue = TurnQueue()
    items = [contribution(index * 10) for index in range(TURN_QUEUE_SOFT_LIMIT + 4)]
    for count, item in enumerate(items, start=1):
        queue.put(item)
        assert len(queue) == count
        assert queue.falling_behind is (count > TURN_QUEUE_SOFT_LIMIT)
    taken = []
    while len(queue) > TURN_QUEUE_SOFT_LIMIT:
        assert queue.falling_behind is True
        taken.append(queue.take(timeout=0))
    assert len(queue) == TURN_QUEUE_SOFT_LIMIT
    assert queue.falling_behind is False  # cleared at the limit
    taken += drain(queue)
    assert taken == items  # all ten, in order, none dropped


def test_old_items_do_not_expire():
    queue = TurnQueue()
    stale = contribution(-3_600_000)  # an hour before T0
    queue.put(stale)
    queue.put(contribution(0))
    assert queue.take(timeout=0) is stale


def test_take_waits_for_a_put_from_another_thread():
    queue = TurnQueue()
    item = contribution(0)
    threading.Timer(0.05, queue.put, args=(item,)).start()
    assert queue.take(timeout=5) is item


def test_concurrent_puts_from_both_inputs_lose_nothing():
    queue = TurnQueue()
    per_input = 200

    def produce(role: MeetingRole, offset: int) -> None:
        for index in range(per_input):
            queue.put(contribution(index * 2 + offset, role))

    threads = [
        threading.Thread(target=produce, args=(MeetingRole.TABLE_CAPTURE, 0)),
        threading.Thread(target=produce, args=(MeetingRole.USER_CAPTURE, 1)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    items = drain(queue)
    assert len(items) == 2 * per_input
    assert [item.ended_at for item in items] == sorted(item.ended_at for item in items)


@pytest.mark.parametrize("role", [MeetingRole.TABLE_RENDER, MeetingRole.LOCAL_RENDER])
def test_contribution_role_must_be_a_capture(role):
    with pytest.raises(ValueError):
        contribution(0, role)
