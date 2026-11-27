from __future__ import annotations

import threading
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Protocol

from lianiq.audio.endpoints import EndpointInventory
from lianiq.call_bridge.contracts import (
    AudioEndpointRef,
    BridgeEvent,
    BridgeEventKind,
    BridgeState,
    CallBridgeLanes,
    EndpointRole,
    LaneId,
    validate_endpoint_assignments,
)
from lianiq.languages.capabilities import CapabilityCatalog, DirectedEdge
from lianiq.languages.errors import ModeUnavailableError, UnsupportedModeError
from lianiq.languages.modes import SessionPair
from lianiq.languages.requirements import DeviceReadiness, ModeAvailability, check


def check_call_bridge(
    session: SessionPair,
    catalog: CapabilityCatalog,
    assigned_roles: Iterable[EndpointRole],
) -> ModeAvailability:
    """Requirement row 7: both recognisers, both edges, both voices and four endpoints.

    ``missing`` names every unmet requirement in display order (models, then endpoints).
    """
    if not session.mode.call_bridge:
        raise UnsupportedModeError("Requirement row 7 applies to Call Bridge sessions only")
    devices = DeviceReadiness(call_endpoints=frozenset(role.value for role in assigned_roles))
    return check(session, catalog, devices)


_OUTBOUND_ROLES = frozenset({EndpointRole.LOCAL_MICROPHONE, EndpointRole.CALL_MICROPHONE_RENDER})
_INBOUND_ROLES = frozenset({EndpointRole.CALL_SPEAKER_CAPTURE, EndpointRole.LOCAL_HEADPHONES})


class LanePort(Protocol):
    generation: int  # set by the controller at each start; stamped on the lane's events

    @property
    def edge(self) -> DirectedEdge: ...

    def start(self) -> None: ...

    def stop(self, timeout: float = 10.0) -> bool: ...

    def set_available(self, available: bool) -> None: ...


class CapturePort(Protocol):
    def start(self) -> None: ...

    def stop(self) -> None: ...


class RecoverablePort(Protocol):
    def rebind(self, endpoint: AudioEndpointRef) -> None: ...


@dataclass(frozen=True, slots=True)
class LaneStopResult:
    """Which lanes ended within their bound (session-status-truthfulness §2.2.4)."""

    outbound_stopped: bool
    inbound_stopped: bool

    @property
    def stopped(self) -> bool:
        return self.outbound_stopped and self.inbound_stopped

    @property
    def timed_out(self) -> tuple[LaneId, ...]:
        flags = ((LaneId.OUTBOUND, self.outbound_stopped), (LaneId.INBOUND, self.inbound_stopped))
        return tuple(lane for lane, stopped in flags if not stopped)


class FullDuplexBridgeController:
    def __init__(
        self,
        assignments: Mapping[EndpointRole, AudioEndpointRef],
        outbound_lane: LanePort,
        inbound_lane: LanePort,
        outbound_capture: CapturePort,
        inbound_capture: CapturePort,
        on_event: Callable[[BridgeEvent], None] | None = None,
        endpoint_ports: Mapping[EndpointRole, RecoverablePort] | None = None,
        *,
        session: SessionPair,
        catalog: CapabilityCatalog,
    ) -> None:
        # The lanes are fixed for the session: local>remote outbound, remote>local inbound.
        self.lanes = CallBridgeLanes.from_session(session)
        if outbound_lane.edge != self.lanes.outbound or inbound_lane.edge != self.lanes.inbound:
            raise ValueError(
                "Call Bridge lanes must be "
                f"{self.lanes.outbound.key} (outbound) and {self.lanes.inbound.key} (inbound)"
            )
        self.session = session
        self.catalog = catalog
        self.assignments = dict(assignments)
        self.outbound_lane = outbound_lane
        self.inbound_lane = inbound_lane
        self.outbound_capture = outbound_capture
        self.inbound_capture = inbound_capture
        self.on_event = on_event
        self.endpoint_ports = dict(endpoint_ports or {})
        self._lost_roles: set[EndpointRole] = set()
        self.state = BridgeState.STOPPED
        self.generation = 0  # the current start generation, stamped on every event
        self._stop_threads: list[threading.Thread] = []

    @property
    def lost_roles(self) -> frozenset[EndpointRole]:
        return frozenset(self._lost_roles)

    def start(self, generation: int | None = None) -> None:
        """Start both lanes; ``generation`` (default: the previous one + 1) stamps every event.

        The Call Bridge workspace passes its ``ActiveSessionOwner`` generation, so stale
        events of an earlier start are recognisable (CAP-0166 AC-08).
        """
        if self.state is BridgeState.RUNNING:
            return
        self.generation = self.generation + 1 if generation is None else generation
        for lane in (self.outbound_lane, self.inbound_lane):
            lane.generation = self.generation
        self._set_state(BridgeState.VALIDATING_ENDPOINTS)
        try:
            # Fail closed before any lane or capture starts, naming every missing item.
            availability = check_call_bridge(self.session, self.catalog, self.assignments)
            if not availability.available:
                raise ModeUnavailableError(availability.missing)
            validate_endpoint_assignments(self.assignments)
        except Exception:
            self._set_state(BridgeState.STOPPED)
            raise
        started: list[object] = []
        try:
            for component in (
                self.outbound_lane,
                self.inbound_lane,
                self.outbound_capture,
                self.inbound_capture,
            ):
                component.start()
                started.append(component)
        except Exception:
            for component in reversed(started):
                if component in {self.outbound_lane, self.inbound_lane}:
                    component.stop(timeout=2.0)
                else:
                    component.stop()
            self._set_state(BridgeState.STOPPED)
            raise
        self._set_state(BridgeState.RUNNING)

    def stop(self, timeout: float = 10.0) -> bool:
        """Stop both captures, then both lanes in parallel; ``True`` if both lanes ended."""
        if self.state is BridgeState.STOPPED:
            return True
        self.stop_captures()
        return self.stop_lanes(timeout).stopped

    def stop_captures(self) -> None:
        """*Stopping*: close both captures (GUI thread, fast); the lanes still run."""
        if self.state is BridgeState.STOPPED:
            return
        self._set_state(BridgeState.STOPPING)
        self.outbound_capture.stop()
        self.inbound_capture.stop()

    def stop_lanes(self, timeout: float = 10.0) -> LaneStopResult:
        """Stop both lanes in parallel, each bounded by ``timeout`` (call off the GUI thread).

        A lane whose ``stop`` does not return within the bound counts as not stopped;
        ``alive()`` stays true while its worker or its stop call still runs.
        """
        results: dict[LaneId, bool] = {}

        def stop_one(lane_id: LaneId, lane: LanePort) -> None:
            results[lane_id] = bool(lane.stop(timeout=timeout))

        lanes = ((LaneId.OUTBOUND, self.outbound_lane), (LaneId.INBOUND, self.inbound_lane))
        self._stop_threads = [
            threading.Thread(
                target=stop_one, args=pair, name=f"call-bridge-stop-{pair[0].value}", daemon=True
            )
            for pair in lanes
        ]
        for thread in self._stop_threads:
            thread.start()
        for thread in self._stop_threads:
            thread.join(timeout=timeout + 0.5)  # also bounds a stop call that never returns
        result = LaneStopResult(
            results.get(LaneId.OUTBOUND, False), results.get(LaneId.INBOUND, False)
        )
        self._set_state(BridgeState.STOPPED if result.stopped else BridgeState.DEGRADED)
        return result

    def alive(self) -> bool:
        """A lane worker or a lane stop call of this controller still runs (linger probe)."""
        if any(thread.is_alive() for thread in self._stop_threads):
            return True
        lanes = (self.outbound_lane, self.inbound_lane)
        return any(getattr(lane, "running", False) for lane in lanes)

    def endpoint_lost(self, role: EndpointRole) -> None:
        self._lost_roles.add(role)
        if role in {
            EndpointRole.LOCAL_MICROPHONE,
            EndpointRole.CALL_MICROPHONE_RENDER,
        }:
            self.outbound_lane.set_available(False)
            self.outbound_capture.stop()
            lane_id = LaneId.OUTBOUND
        else:
            self.inbound_lane.set_available(False)
            self.inbound_capture.stop()
            lane_id = LaneId.INBOUND
        self._set_state(BridgeState.DEGRADED)
        self._emit(lane_id, BridgeEventKind.ENDPOINT, "endpoint_lost", "lane_muted")

    def endpoint_recovered(self, role: EndpointRole, endpoint: AudioEndpointRef) -> None:
        """Rebind ``role``; *Listening* (``endpoint_recovered``) only once its lane is whole.

        While the lane's other endpoint is still lost, the lane stays muted and the event is
        ``endpoint_lost`` again, so its status names the device that is still missing.
        """
        configured = self.assignments[role]
        if endpoint.endpoint_id != configured.endpoint_id:
            raise ValueError("Recovered endpoint identity does not match configured endpoint")
        if endpoint.flow is not configured.flow:
            raise ValueError("Recovered endpoint flow does not match configured endpoint")
        port = self.endpoint_ports.get(role)
        lane_id = LaneId.OUTBOUND if role in _OUTBOUND_ROLES else LaneId.INBOUND
        self._emit(lane_id, BridgeEventKind.ENDPOINT, "endpoint_reconnecting", "lane_reconnecting")
        if port is not None:
            port.rebind(endpoint)
        self.assignments[role] = endpoint
        self._lost_roles.discard(role)
        lane_roles = _OUTBOUND_ROLES if lane_id is LaneId.OUTBOUND else _INBOUND_ROLES
        restored = not self._lost_roles.intersection(lane_roles)
        if restored and lane_id is LaneId.OUTBOUND:
            self.outbound_lane.set_available(True)
            self.outbound_capture.start()
        elif restored:
            self.inbound_lane.set_available(True)
            self.inbound_capture.start()
        if not self._lost_roles:
            self._set_state(BridgeState.RUNNING)
        if restored:
            self._emit(lane_id, BridgeEventKind.ENDPOINT, "endpoint_recovered", "lane_restored")
        else:  # the lane's other endpoint is still lost: the lane stays muted
            self._emit(lane_id, BridgeEventKind.ENDPOINT, "endpoint_lost", "lane_muted")

    def reconcile_endpoints(self, inventory: EndpointInventory) -> None:
        for role, configured in tuple(self.assignments.items()):
            try:
                current = inventory.resolve(configured.endpoint_id, configured.flow)
            except LookupError:
                if role not in self._lost_roles:
                    self.endpoint_lost(role)
                continue
            if role in self._lost_roles:
                self.endpoint_recovered(role, current)

    def _set_state(self, state: BridgeState) -> None:
        self.state = state
        self._emit(None, BridgeEventKind.STATE, state.value, "state_changed")

    def _emit(
        self,
        lane_id: LaneId | None,
        kind: BridgeEventKind,
        category: str,
        message: str,
    ) -> None:
        if self.on_event:
            self.on_event(BridgeEvent(lane_id, kind, category, message, None, self.generation))
