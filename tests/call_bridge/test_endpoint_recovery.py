from __future__ import annotations

from dataclasses import replace

from lianiq.audio.endpoints import EndpointInventory
from lianiq.call_bridge.contracts import (
    AudioEndpointRef,
    BridgeState,
    CallBridgeLanes,
    EndpointFlow,
    EndpointRole,
)
from lianiq.call_bridge.controller import FullDuplexBridgeController
from tests.call_bridge.support import call_bridge_session, ready_catalog

SESSION = call_bridge_session()
LANES = CallBridgeLanes.from_session(SESSION)


def endpoint(role: EndpointRole, index: int) -> AudioEndpointRef:
    flow = (
        EndpointFlow.CAPTURE
        if role in {EndpointRole.LOCAL_MICROPHONE, EndpointRole.CALL_SPEAKER_CAPTURE}
        else EndpointFlow.RENDER
    )
    return AudioEndpointRef(f"id-{role.value}", role.value, flow, "WASAPI", index)


class FakeLane:
    def __init__(self, edge):
        self.edge = edge
        self.available = True

    def start(self):
        return None

    def stop(self, timeout=10.0):
        return True

    def set_available(self, available):
        self.available = available


class RecoverablePort:
    def __init__(self):
        self.running = False
        self.endpoint = None

    def start(self):
        self.running = True

    def stop(self):
        self.running = False

    def rebind(self, endpoint):
        self.endpoint = endpoint


def test_same_stable_endpoint_rebinds_to_new_runtime_index(tmp_path) -> None:
    assignments = {role: endpoint(role, index) for index, role in enumerate(EndpointRole)}
    outbound = FakeLane(LANES.outbound)
    inbound = FakeLane(LANES.inbound)
    tx_capture = RecoverablePort()
    rx_capture = RecoverablePort()
    ports = {role: RecoverablePort() for role in EndpointRole}
    ports[EndpointRole.LOCAL_MICROPHONE] = tx_capture
    ports[EndpointRole.CALL_SPEAKER_CAPTURE] = rx_capture
    controller = FullDuplexBridgeController(
        assignments,
        outbound,
        inbound,
        tx_capture,
        rx_capture,
        endpoint_ports=ports,
        session=SESSION,
        catalog=ready_catalog(tmp_path, SESSION),
    )
    controller.start()
    controller.endpoint_lost(EndpointRole.CALL_SPEAKER_CAPTURE)
    returned = replace(assignments[EndpointRole.CALL_SPEAKER_CAPTURE], runtime_index=99)

    controller.endpoint_recovered(EndpointRole.CALL_SPEAKER_CAPTURE, returned)

    assert controller.state is BridgeState.RUNNING
    assert inbound.available is True
    assert rx_capture.endpoint.runtime_index == 99
    assert rx_capture.running is True


def test_inventory_reconciliation_fails_closed_then_recovers(tmp_path) -> None:
    assignments = {role: endpoint(role, index) for index, role in enumerate(EndpointRole)}
    outbound = FakeLane(LANES.outbound)
    inbound = FakeLane(LANES.inbound)
    tx_capture = RecoverablePort()
    rx_capture = RecoverablePort()
    ports = {role: RecoverablePort() for role in EndpointRole}
    ports[EndpointRole.LOCAL_MICROPHONE] = tx_capture
    ports[EndpointRole.CALL_SPEAKER_CAPTURE] = rx_capture
    controller = FullDuplexBridgeController(
        assignments,
        outbound,
        inbound,
        tx_capture,
        rx_capture,
        endpoint_ports=ports,
        session=SESSION,
        catalog=ready_catalog(tmp_path, SESSION),
    )
    controller.start()
    without_rx = EndpointInventory(
        value
        for role, value in assignments.items()
        if role is not EndpointRole.CALL_SPEAKER_CAPTURE
    )

    controller.reconcile_endpoints(without_rx)
    assert EndpointRole.CALL_SPEAKER_CAPTURE in controller.lost_roles
    assert controller.state is BridgeState.DEGRADED

    returned = replace(assignments[EndpointRole.CALL_SPEAKER_CAPTURE], runtime_index=88)
    controller.reconcile_endpoints(EndpointInventory([*without_rx.endpoints, returned]))
    assert controller.lost_roles == frozenset()
    assert controller.state is BridgeState.RUNNING
    assert rx_capture.endpoint.runtime_index == 88


def test_recovering_one_of_two_lost_lane_endpoints_keeps_the_lane_lost(tmp_path) -> None:
    """WI-01 advisory: *Listening* only once the lane is whole again (CAP-0166 AC-11)."""
    from lianiq.call_bridge.contracts import BridgeEventKind, LaneId
    from lianiq.call_bridge.lane_status import LaneActivity, LaneStatusBook

    assignments = {role: endpoint(role, index) for index, role in enumerate(EndpointRole)}
    inbound, capture, events = FakeLane(LANES.inbound), RecoverablePort(), []
    controller = FullDuplexBridgeController(
        assignments,
        FakeLane(LANES.outbound),
        inbound,
        RecoverablePort(),
        capture,
        on_event=events.append,
        endpoint_ports={role: RecoverablePort() for role in EndpointRole},
        session=SESSION,
        catalog=ready_catalog(tmp_path, SESSION),
    )
    book = LaneStatusBook()
    book.reset(5)
    controller.start(generation=5)
    controller.endpoint_lost(EndpointRole.CALL_SPEAKER_CAPTURE)
    controller.endpoint_lost(EndpointRole.LOCAL_HEADPHONES)
    del events[:]
    controller.endpoint_recovered(
        EndpointRole.CALL_SPEAKER_CAPTURE, assignments[EndpointRole.CALL_SPEAKER_CAPTURE]
    )
    endpoint_events = [e.category for e in events if e.kind is BridgeEventKind.ENDPOINT]
    assert endpoint_events == ["endpoint_reconnecting", "endpoint_lost"]
    assert inbound.available is False and capture.running is False
    for event in events:
        book.apply(event, "Headphones")
    assert book.statuses[LaneId.INBOUND].activity is LaneActivity.DEVICE_LOST
    assert book.statuses[LaneId.INBOUND].detail == "Headphones"
    controller.endpoint_recovered(
        EndpointRole.LOCAL_HEADPHONES, assignments[EndpointRole.LOCAL_HEADPHONES]
    )
    assert events[-1].category == "endpoint_recovered" and inbound.available is True
    book.apply(events[-1])
    assert book.statuses[LaneId.INBOUND].activity is LaneActivity.LISTENING
