"""Lane status lines, live call text and bridge notices of ``CallBridgeWorkspace``.

CAP-0166 WI-03 (spec §2.3, §3.2; AC-07, AC-08, AC-11, AC-13): one ``LaneStatusBook`` drives
both path boxes' status lines. ``reset_status`` runs at Start with the session owner
generation, which the controller stamps on every event, so events of an earlier start are
ignored. Route-test results arrive on their own signal and never reach the book. A lost
endpoint names its device (``controller.lost_roles`` and the assignments); only that lane
changes. Completed turns arrive on ``call_bridge_result`` and go to the live text view only,
never to the Conversation transcript.

session-status-truthfulness WI-05 (§2.2.4, AC-19): a lane whose stop timed out reads
``LANE_DID_NOT_STOP`` instead of *Stopped* until the next Start; a result is stamped with its
start generation and dropped unless that start is still live (a late result is not shown).
"""

from __future__ import annotations

from PySide6.QtCore import Slot

from lianiq.call_bridge.contracts import (
    BridgeEvent,
    BridgeEventKind,
    CallBridgeLanes,
    EndpointRole,
    LaneId,
)
from lianiq.call_bridge.lane_status import LaneActivity, LaneStatus, LaneStatusBook
from lianiq.call_bridge.route_tests import PATH_ROLES
from lianiq.domain import TranslationResult
from lianiq.languages.modes import SessionPair
from lianiq.ui import notice_catalog as catalog
from lianiq.ui import strings_call_bridge as s
from lianiq.ui.strings_session import LANE_DID_NOT_STOP

_TEXTS = {
    LaneActivity.STOPPED: s.CB_LANE_STOPPED,
    LaneActivity.STARTING: s.CB_LANE_STARTING,
    LaneActivity.LISTENING: s.CB_LANE_LISTENING,
    LaneActivity.TRANSLATING: s.CB_LANE_TRANSLATING,
    LaneActivity.SPEAKING: s.CB_LANE_SPEAKING,
    LaneActivity.ECHO_PAUSED: s.CB_LANE_ECHO_PAUSED,
    LaneActivity.RECONNECTING: s.CB_LANE_RECONNECTING,
}


def lane_status_text(status: LaneStatus) -> str:
    if status.activity is LaneActivity.MUTED:
        return s.CB_LANE_MUTED.format(reason=status.detail)
    if status.activity is LaneActivity.DEVICE_LOST:
        return s.CB_LANE_DEVICE_LOST.format(device=status.detail)
    return _TEXTS[status.activity]


class CallBridgeStatus:
    """``CallBridgeWorkspace`` mixin: lane status lines, live text and event notices."""

    def init_status(self) -> None:
        self.lane_status = LaneStatusBook()
        self._text_lanes: CallBridgeLanes | None = None
        self.host.bridge.call_bridge_result.connect(self._show_call_bridge_result)

    def reset_status(self, generation: int, session: SessionPair) -> None:
        """A new Start: both lanes *Starting…*, only ``generation`` counts, text cleared."""
        self.lane_status.reset(generation)
        self._text_lanes = CallBridgeLanes.from_session(session)
        self._results_generation = generation
        self._lanes_not_stopped = frozenset()
        self.panel.text_view.clear()
        self.show_lane_statuses()

    def stop_status(self) -> None:
        self.lane_status.stop()
        self.show_lane_statuses()

    def show_lane_statuses(self) -> None:
        for lane, status in self.lane_status.statuses.items():
            text = lane_status_text(status)
            if lane in self._lanes_not_stopped and status.activity is LaneActivity.STOPPED:
                text = LANE_DID_NOT_STOP  # never *Stopped* while its worker may still run
            self.panel.paths[lane].set_lane_status(text)

    def _lost_device(self, lane: LaneId) -> str:
        """The display name of the lane's lost endpoint (capture first), else ``""``."""
        controller = self.controller
        if controller is None:
            return ""
        lost = controller.lost_roles
        role = next((role for role in PATH_ROLES[lane] if role in lost), None)
        return "" if role is None else controller.assignments[role].display_name

    @Slot(int, object)
    def _show_call_bridge_result(self, generation: int, result: TranslationResult) -> None:
        lanes = self._text_lanes
        if lanes is None or generation != self._results_generation:
            return
        outbound = result.source_language == lanes.outbound.source
        self.panel.text_view.add_turn(LaneId.OUTBOUND if outbound else LaneId.INBOUND, result)

    @Slot(object, str)
    def _handle_call_bridge_capture_fault(self, role: EndpointRole, message: str) -> None:
        if self.controller is not None:
            self.controller.endpoint_lost(role)
        lane = LaneId.OUTBOUND if role is EndpointRole.LOCAL_MICROPHONE else LaneId.INBOUND
        self.host.post_notice(
            catalog.bridge_capture_muted(message, self._lane_source(lane), lane.value)
        )

    @Slot(object)
    def _show_call_bridge_event(self, event: BridgeEvent) -> None:
        lost = event.kind is BridgeEventKind.ENDPOINT and event.category == "endpoint_lost"
        detail = self._lost_device(event.lane_id) if lost and event.lane_id else ""
        if self.lane_status.apply(event, detail) is not None or event.lane_id is None:
            self.show_lane_statuses()
        lane = event.lane_id.value if event.lane_id else None
        where = self._lane_source(event.lane_id)
        if lost and detail and event.generation == self.lane_status.generation:
            title = s.CB_LANE_DEVICE_LOST.format(device=detail)
            self.host.post_notice(catalog.bridge_failed(lane, title, where))
        elif event.kind is BridgeEventKind.ERROR:
            if event.category == "playback_failure" and self.controller is not None:
                output_role = PATH_ROLES[event.lane_id][1]
                self.controller.endpoint_lost(output_role)
            self.host.diagnostics.record("call-bridge", f"{event.category}: {event.message}")
            self.host.post_notice(catalog.bridge_failed(lane, event.category, where))
        elif event.kind is BridgeEventKind.DROPPED:
            self.host.post_notice(catalog.bridge_dropped(event.category, where, lane))
