"""CAP-0166 AC-12: the outbound capture is muted from playback start to end + tail."""

from __future__ import annotations

import pytest

from lianiq.call_bridge.echo_guard import EchoGuard


class Clock:
    def __init__(self) -> None:
        self.now = 10.0

    def __call__(self) -> float:
        return self.now


def test_muted_from_playback_start_until_finish_plus_tail() -> None:
    clock = Clock()
    guard = EchoGuard(guard_tail_ms=300, clock=clock)
    assert not guard.outbound_muted()
    guard.playback_started()
    clock.now = 20.0
    assert guard.outbound_muted()
    guard.playback_finished()
    clock.now = 20.29
    assert guard.outbound_muted()
    assert not guard.outbound_muted(20.31)  # an explicit ``now`` wins over the clock
    clock.now = 20.4
    assert not guard.outbound_muted()


def test_overlapping_playbacks_keep_the_guard_until_the_last_finishes() -> None:
    clock = Clock()
    guard = EchoGuard(guard_tail_ms=0, clock=clock)
    guard.playback_started()
    guard.playback_started()
    guard.playback_finished()
    assert guard.outbound_muted()
    guard.playback_finished()
    assert not guard.outbound_muted()


def test_negative_tail_is_rejected() -> None:
    with pytest.raises(ValueError, match="guard_tail_ms"):
        EchoGuard(guard_tail_ms=-1)
