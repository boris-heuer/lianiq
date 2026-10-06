from __future__ import annotations

from dataclasses import replace

import pytest

from offline_translator.call_bridge.contracts import (
    AudioEndpointRef,
    BridgeState,
    EndpointFlow,
    EndpointRole,
    validate_endpoint_assignments,
)
from offline_translator.call_bridge.controller import FullDuplexBridgeController


def endpoint(role: EndpointRole, index: int) -> AudioEndpointRef:
    flow = (
        EndpointFlow.CAPTURE
        if role in {EndpointRole.LOCAL_MICROPHONE, EndpointRole.CALL_SPEAKER_CAPTURE}
        else EndpointFlow.RENDER
    )
    return AudioEndpointRef(f"id-{role.value}", f"Device {role.value}", flow, "WASAPI", index)


class FakeLane:
    def __init__(self) -> None:
        self.started = False
        self.available = True

    def start(self) -> None:
        self.started = True

    def stop(self, timeout=10.0) -> bool:
        self.started = False
        return True

    def set_available(self, available: bool) -> None:
        self.available = available


class FakeCapture:
    def __init__(self) -> None:
        self.running = False

    def start(self) -> None:
        self.running = True

    def stop(self) -> None:
        self.running = False


def mapping():
    return {role: endpoint(role, index) for index, role in enumerate(EndpointRole)}


def test_endpoint_roles_reject_wrong_flow_and_reuse() -> None:
    assignments = mapping()
    assignments[EndpointRole.LOCAL_HEADPHONES] = replace(
        assignments[EndpointRole.LOCAL_HEADPHONES], flow=EndpointFlow.CAPTURE
    )
    with pytest.raises(ValueError, match="render"):
        validate_endpoint_assignments(assignments)

    assignments = mapping()
    assignments[EndpointRole.LOCAL_HEADPHONES] = replace(
        assignments[EndpointRole.LOCAL_HEADPHONES],
        endpoint_id=assignments[EndpointRole.CALL_MICROPHONE_RENDER].endpoint_id,
    )
    with pytest.raises(ValueError, match="assigned more than once"):
        validate_endpoint_assignments(assignments)


def test_endpoint_loss_degrades_only_affected_lane_and_never_falls_back() -> None:
    outbound = FakeLane()
    inbound = FakeLane()
    tx_capture = FakeCapture()
    rx_capture = FakeCapture()
    controller = FullDuplexBridgeController(mapping(), outbound, inbound, tx_capture, rx_capture)
    controller.start()

    controller.endpoint_lost(EndpointRole.CALL_SPEAKER_CAPTURE)

    assert controller.state is BridgeState.DEGRADED
    assert outbound.available is True
    assert inbound.available is False
    assert tx_capture.running is True
    assert rx_capture.running is False


def test_start_stop_controls_both_lanes_and_capture_ports() -> None:
    outbound = FakeLane()
    inbound = FakeLane()
    tx_capture = FakeCapture()
    rx_capture = FakeCapture()
    controller = FullDuplexBridgeController(mapping(), outbound, inbound, tx_capture, rx_capture)

    controller.start()
    assert controller.state is BridgeState.RUNNING
    assert outbound.started and inbound.started
    assert tx_capture.running and rx_capture.running

    assert controller.stop(timeout=1.0)
    assert controller.state is BridgeState.STOPPED
    assert not tx_capture.running and not rx_capture.running
