from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Protocol

from lianiq.audio.endpoints import EndpointInventory
from lianiq.call_bridge.contracts import (
    AudioEndpointRef,
    BridgeEvent,
    BridgeEventKind,
    BridgeState,
    EndpointRole,
    LaneId,
    validate_endpoint_assignments,
)


class LanePort(Protocol):
    def start(self) -> None: ...

    def stop(self, timeout: float = 10.0) -> bool: ...

    def set_available(self, available: bool) -> None: ...


class CapturePort(Protocol):
    def start(self) -> None: ...

    def stop(self) -> None: ...


class RecoverablePort(Protocol):
    def rebind(self, endpoint: AudioEndpointRef) -> None: ...


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
    ) -> None:
        self.assignments = dict(assignments)
        self.outbound_lane = outbound_lane
        self.inbound_lane = inbound_lane
        self.outbound_capture = outbound_capture
        self.inbound_capture = inbound_capture
        self.on_event = on_event
        self.endpoint_ports = dict(endpoint_ports or {})
        self._lost_roles: set[EndpointRole] = set()
        self.state = BridgeState.STOPPED

    @property
    def lost_roles(self) -> frozenset[EndpointRole]:
        return frozenset(self._lost_roles)

    def start(self) -> None:
        if self.state is BridgeState.RUNNING:
            return
        self._set_state(BridgeState.VALIDATING_ENDPOINTS)
        validate_endpoint_assignments(self.assignments)
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
        if self.state is BridgeState.STOPPED:
            return True
        self._set_state(BridgeState.STOPPING)
        self.outbound_capture.stop()
        self.inbound_capture.stop()
        outbound_stopped = self.outbound_lane.stop(timeout=timeout)
        inbound_stopped = self.inbound_lane.stop(timeout=timeout)
        stopped = outbound_stopped and inbound_stopped
        self._set_state(BridgeState.STOPPED if stopped else BridgeState.DEGRADED)
        return stopped

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
        configured = self.assignments[role]
        if endpoint.endpoint_id != configured.endpoint_id:
            raise ValueError("Recovered endpoint identity does not match configured endpoint")
        if endpoint.flow is not configured.flow:
            raise ValueError("Recovered endpoint flow does not match configured endpoint")
        port = self.endpoint_ports.get(role)
        if port is not None:
            port.rebind(endpoint)
        self.assignments[role] = endpoint
        self._lost_roles.discard(role)
        if role in {
            EndpointRole.LOCAL_MICROPHONE,
            EndpointRole.CALL_MICROPHONE_RENDER,
        }:
            if not self._lost_roles.intersection(
                {EndpointRole.LOCAL_MICROPHONE, EndpointRole.CALL_MICROPHONE_RENDER}
            ):
                self.outbound_lane.set_available(True)
                self.outbound_capture.start()
            lane_id = LaneId.OUTBOUND
        else:
            if not self._lost_roles.intersection(
                {EndpointRole.CALL_SPEAKER_CAPTURE, EndpointRole.LOCAL_HEADPHONES}
            ):
                self.inbound_lane.set_available(True)
                self.inbound_capture.start()
            lane_id = LaneId.INBOUND
        if not self._lost_roles:
            self._set_state(BridgeState.RUNNING)
        self._emit(lane_id, BridgeEventKind.ENDPOINT, "endpoint_recovered", "lane_restored")

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
            self.on_event(BridgeEvent(lane_id, kind, category, message))
