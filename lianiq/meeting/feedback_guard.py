"""Cross-device feedback guard keyed by output target (CAP-0177 contract.md §4).

Qt-free and thread-safe; time comes from the injected ``clock`` (seconds, monotonic).
``muted_by(target)`` names the captures muted from playback start until playback end +
``guard_tail_ms``:

=================================================  =========================  ================
Playback target                                    ``mute`` (default)         ``open``
=================================================  =========================  ================
``TABLE_RENDER`` (table-language speech)           user and table capture     user capture
``LOCAL_RENDER``, not marked as headset            table and user capture     table and user
``LOCAL_RENDER``, marked as headset                none                       none
=================================================  =========================  ================

A muted capture discards its frames and resets its segmenter (the controller's job); muted
audio never becomes a contribution. ``before_playback`` waits while a capture the target will
mute is speaking, for at most ``max_playback_defer_ms`` since ``waiting_since``; then the
running contribution is closed and the output plays. Captures the target does not mute are
never waited for. Playbacks never overlap: the single inference worker serialises them.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from enum import StrEnum

from lianiq.meeting.contracts import (
    CAPTURE_ROLES,
    RENDER_ROLES,
    MeetingRole,
    TableInputDuringOutput,
)

_BOTH = frozenset({MeetingRole.USER_CAPTURE, MeetingRole.TABLE_CAPTURE})


class PlaybackDecision(StrEnum):
    PLAY = "play"
    WAIT = "wait"
    CLOSE_AND_PLAY = "close_and_play"  # flush the running segments, process them, then play


class FeedbackGuard:
    def __init__(
        self,
        table_input_during_output: TableInputDuringOutput,
        local_render_is_headset: bool,
        guard_tail_ms: int,
        max_playback_defer_ms: int,
        clock: Callable[[], float],
    ) -> None:
        if guard_tail_ms < 0 or max_playback_defer_ms < 0:
            raise ValueError("guard_tail_ms and max_playback_defer_ms must not be negative")
        table_render = (
            _BOTH
            if table_input_during_output is TableInputDuringOutput.MUTE
            else frozenset({MeetingRole.USER_CAPTURE})
        )
        self._muted_by = {
            MeetingRole.TABLE_RENDER: table_render,
            MeetingRole.LOCAL_RENDER: frozenset() if local_render_is_headset else _BOTH,
        }
        self._tail = guard_tail_ms / 1000.0
        self._max_defer = max_playback_defer_ms / 1000.0
        self._clock = clock
        self._lock = threading.Lock()
        self._playing: set[MeetingRole] = set()
        self._tail_until: dict[MeetingRole, float] = {}

    def muted_by(self, target: MeetingRole) -> frozenset[MeetingRole]:
        if target not in RENDER_ROLES:
            raise ValueError(f"A playback target is a render role, not {target}")
        return self._muted_by[target]

    def is_muted(self, capture: MeetingRole) -> bool:
        if capture not in CAPTURE_ROLES:
            raise ValueError(f"Only a capture role can be muted, not {capture}")
        now = self._clock()
        with self._lock:
            return any(
                capture in muted
                and (target in self._playing or now < self._tail_until.get(target, now))
                for target, muted in self._muted_by.items()
            )

    def before_playback(
        self, target: MeetingRole, speaking: frozenset[MeetingRole], waiting_since: float
    ) -> PlaybackDecision:
        if not self.muted_by(target) & speaking:
            return PlaybackDecision.PLAY
        if self._clock() - waiting_since < self._max_defer:
            return PlaybackDecision.WAIT
        return PlaybackDecision.CLOSE_AND_PLAY

    def playback_started(self, target: MeetingRole) -> None:
        self.muted_by(target)  # validates the target
        with self._lock:
            self._playing.add(target)

    def playback_ended(self, target: MeetingRole) -> None:
        """Ends the playback; its captures stay muted for the guard tail."""
        self.muted_by(target)
        now = self._clock()
        with self._lock:
            self._playing.discard(target)
            self._tail_until[target] = now + self._tail
