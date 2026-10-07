from __future__ import annotations

from dataclasses import replace

from lianiq.audio.endpoints import EndpointInventory
from lianiq.call_bridge.contracts import (
    AudioEndpointRef,
    BridgeState,
    EndpointFlow,
    EndpointRole,
)
from lianiq.call_bridge.controller import FullDuplexBridgeController


def endpoint(role: EndpointRole, index: int) -> AudioEndpointRef:
    flow = (
        EndpointFlow.CAPTURE
        if role in {EndpointRole.LOCAL_MICROPHONE, EndpointRole.CALL_SPEAKER_CAPTURE}
        else EndpointFlow.RENDER
    )
    return AudioEndpointRef(f"id-{role.value}", role.value, flow, "WASAPI", index)


class FakeLane:
    def __init__(self):
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


def test_same_stable_endpoint_rebinds_to_new_runtime_index() -> None:
    assignments = {role: endpoint(role, index) for index, role in enumerate(EndpointRole)}
    outbound = FakeLane()
    inbound = FakeLane()
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
    )
    controller.start()
    controller.endpoint_lost(EndpointRole.CALL_SPEAKER_CAPTURE)
    returned = replace(assignments[EndpointRole.CALL_SPEAKER_CAPTURE], runtime_index=99)

    controller.endpoint_recovered(EndpointRole.CALL_SPEAKER_CAPTURE, returned)

    assert controller.state is BridgeState.RUNNING
    assert inbound.available is True
    assert rx_capture.endpoint.runtime_index == 99
    assert rx_capture.running is True


def test_inventory_reconciliation_fails_closed_then_recovers() -> None:
    assignments = {role: endpoint(role, index) for index, role in enumerate(EndpointRole)}
    outbound = FakeLane()
    inbound = FakeLane()
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
