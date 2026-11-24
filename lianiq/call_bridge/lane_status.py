"""Per-lane Call Bridge status from bridge events (CAP-0166 spec §3.1, AC-07, AC-08).

``LaneStatusBook`` keeps one ``LaneStatus`` per lane for the current start generation.
Events of another generation (an earlier start, a route test stamped ``0``) and lane-less
events other than ``STATE`` never change a lane: a route-test result is not a lane activity.
``apply`` returns the new status of the one lane an event changed, else ``None``; a ``STATE``
event (``running``, ``stopped``) changes both lanes, so callers re-read ``statuses``.
Qt-free and not thread-safe: the UI applies events on its own thread.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from lianiq.call_bridge.contracts import BridgeEvent, BridgeEventKind, BridgeState, LaneId


class LaneActivity(StrEnum):
    STOPPED = "stopped"
    STARTING = "starting"
    LISTENING = "listening"
    TRANSLATING = "translating"
    SPEAKING = "speaking"
    ECHO_PAUSED = "echo_paused"  # outbound only
    MUTED = "muted"
    DEVICE_LOST = "device_lost"
    RECONNECTING = "reconnecting"


@dataclass(frozen=True, slots=True)
class LaneStatus:
    lane: LaneId
    activity: LaneActivity
    detail: str = ""  # device display name or mute reason


_ACTIVITY_EVENTS = {
    "listening": LaneActivity.LISTENING,
    "translating": LaneActivity.TRANSLATING,
    "speaking": LaneActivity.SPEAKING,
    "echo_paused": LaneActivity.ECHO_PAUSED,
}
_ENDPOINT_EVENTS = {
    "endpoint_lost": LaneActivity.DEVICE_LOST,
    "endpoint_reconnecting": LaneActivity.RECONNECTING,
    "endpoint_recovered": LaneActivity.LISTENING,
}
# A lane in one of these states ignores activity events: a late ``listening`` after Stop or
# after a device loss must not hide them.
_STICKY = frozenset({LaneActivity.STOPPED, LaneActivity.DEVICE_LOST, LaneActivity.RECONNECTING})


class LaneStatusBook:
    def __init__(self) -> None:
        self._generation = 0
        self._statuses = {lane: LaneStatus(lane, LaneActivity.STOPPED) for lane in LaneId}

    @property
    def generation(self) -> int:
        return self._generation

    @property
    def statuses(self) -> Mapping[LaneId, LaneStatus]:
        return MappingProxyType(dict(self._statuses))

    def reset(self, generation: int) -> None:
        """A new start: only events of ``generation`` count; both lanes are *Starting*."""
        self._generation = generation
        self._set_all(LaneActivity.STARTING)

    def apply(self, event: BridgeEvent, detail: str = "") -> LaneStatus | None:
        """Apply one event; ``detail`` names the lost device of an ``endpoint_lost`` event."""
        if event.generation != self._generation:
            return None
        if event.kind is BridgeEventKind.STATE:
            if event.category == BridgeState.STOPPED.value:
                self._set_all(LaneActivity.STOPPED)
            elif event.category == BridgeState.RUNNING.value:
                for lane, status in self._statuses.items():
                    if status.activity is LaneActivity.STARTING:
                        self._statuses[lane] = LaneStatus(lane, LaneActivity.LISTENING)
            return None
        lane = event.lane_id
        if lane is None:
            return None
        current = self._statuses[lane].activity
        if event.kind is BridgeEventKind.ACTIVITY:
            activity = _ACTIVITY_EVENTS.get(event.category)
            if activity is None or current in _STICKY:
                return None
            return self._set(lane, activity, "")
        if event.kind is BridgeEventKind.ENDPOINT:
            activity = _ENDPOINT_EVENTS.get(event.category)
            if activity is None or current is LaneActivity.STOPPED:
                return None
            return self._set(lane, activity, detail if activity is LaneActivity.DEVICE_LOST else "")
        if event.kind is BridgeEventKind.ERROR and current not in _STICKY:
            return self._set(lane, LaneActivity.MUTED, event.category)
        return None

    def _set(self, lane: LaneId, activity: LaneActivity, detail: str) -> LaneStatus:
        status = self._statuses[lane] = LaneStatus(lane, activity, detail)
        return status

    def _set_all(self, activity: LaneActivity) -> None:
        self._statuses = {lane: LaneStatus(lane, activity) for lane in LaneId}
