from __future__ import annotations

from dataclasses import replace

import pytest

from lianiq.call_bridge.contracts import (
    BridgeState,
    CallBridgeLanes,
    EndpointFlow,
    EndpointRole,
    validate_endpoint_assignments,
)
from lianiq.call_bridge.controller import FullDuplexBridgeController, check_call_bridge
from lianiq.languages import (
    BUILTIN_REGISTRY,
    DirectedEdge,
    InputKind,
    ModeUnavailableError,
    OutputKind,
    RoutingKind,
    SessionPair,
    UnsupportedModeError,
    UsageMode,
    describe,
)
from tests.call_bridge.support import DE, ZH, call_bridge_session, mapping, ready_catalog
from tests.languages.synthetic import QAA, QAB, synthetic_registry


class FakeLane:
    def __init__(self, edge: DirectedEdge) -> None:
        self.edge = edge
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


def bridge(tmp_path, *, session=None, assignments=None, voices=None):
    session = session or call_bridge_session()
    lanes = CallBridgeLanes.from_session(session)
    outbound, inbound = FakeLane(lanes.outbound), FakeLane(lanes.inbound)
    tx_capture, rx_capture = FakeCapture(), FakeCapture()
    controller = FullDuplexBridgeController(
        mapping() if assignments is None else assignments,
        outbound,
        inbound,
        tx_capture,
        rx_capture,
        session=session,
        catalog=ready_catalog(tmp_path, session, voices=voices),
    )
    return controller, outbound, inbound, tx_capture, rx_capture


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


def test_endpoint_loss_degrades_only_affected_lane_and_never_falls_back(tmp_path) -> None:
    controller, outbound, inbound, tx_capture, rx_capture = bridge(tmp_path)
    controller.start()

    controller.endpoint_lost(EndpointRole.CALL_SPEAKER_CAPTURE)

    assert controller.state is BridgeState.DEGRADED
    assert outbound.available is True
    assert inbound.available is False
    assert tx_capture.running is True
    assert rx_capture.running is False


def test_start_stop_controls_both_lanes_and_capture_ports(tmp_path) -> None:
    controller, outbound, inbound, tx_capture, rx_capture = bridge(tmp_path)

    controller.start()
    assert controller.state is BridgeState.RUNNING
    assert outbound.started and inbound.started
    assert tx_capture.running and rx_capture.running

    assert controller.stop(timeout=1.0)
    assert controller.state is BridgeState.STOPPED
    assert not tx_capture.running and not rx_capture.running


@pytest.mark.parametrize(
    ("local", "outbound", "inbound"),
    [(DE, "de>zh-Hans", "zh-Hans>de"), (ZH, "zh-Hans>de", "de>zh-Hans")],
)
def test_ac09_lanes_are_local_to_remote_and_remote_to_local(local, outbound, inbound) -> None:
    lanes = CallBridgeLanes.from_session(call_bridge_session(local))

    assert (lanes.outbound.key, lanes.inbound.key) == (outbound, inbound)
    assert lanes.local == local
    assert lanes.remote == ({DE, ZH} - {local}).pop()


def test_ac09_lanes_follow_any_qualified_pair() -> None:
    registry = synthetic_registry()
    lanes = CallBridgeLanes.from_session(call_bridge_session(QAB, (QAA, QAB), registry))

    assert (lanes.outbound.key, lanes.inbound.key) == ("qab>qaa", "qaa>qab")


def test_lanes_need_a_call_bridge_session_and_opposite_edges() -> None:
    conversation = SessionPair(
        BUILTIN_REGISTRY.pair(DE, ZH),
        UsageMode(InputKind.MICROPHONE, RoutingKind.BIDIRECTIONAL, OutputKind.SPOKEN),
    )
    with pytest.raises(UnsupportedModeError):
        CallBridgeLanes.from_session(conversation)
    with pytest.raises(ValueError, match="two directions"):
        CallBridgeLanes(DirectedEdge(DE, ZH), DirectedEdge(DE, ZH))


def test_ac09_controller_rejects_lanes_that_differ_from_the_session(tmp_path) -> None:
    session = call_bridge_session()
    lanes = CallBridgeLanes.from_session(session)

    with pytest.raises(ValueError, match="de>zh-Hans \\(outbound\\) and zh-Hans>de"):
        FullDuplexBridgeController(
            mapping(),
            FakeLane(lanes.inbound),  # swapped
            FakeLane(lanes.outbound),
            FakeCapture(),
            FakeCapture(),
            session=session,
            catalog=ready_catalog(tmp_path, session),
        )


def test_ac09_missing_voice_and_endpoint_fail_closed_before_any_lane_starts(tmp_path) -> None:
    assignments = mapping()
    del assignments[EndpointRole.CALL_MICROPHONE_RENDER]
    controller, outbound, inbound, tx_capture, rx_capture = bridge(
        tmp_path, assignments=assignments, voices=(DE,)
    )

    with pytest.raises(ModeUnavailableError) as raised:
        controller.start()

    assert [describe(item, BUILTIN_REGISTRY) for item in raised.value.missing] == [
        "voice Mandarin (Simplified)",
        "call microphone endpoint",
    ]
    assert not (outbound.started or inbound.started)
    assert not (tx_capture.running or rx_capture.running)
    assert controller.state is BridgeState.STOPPED


def test_invalid_endpoint_flow_still_fails_closed_and_returns_to_stopped(tmp_path) -> None:
    assignments = mapping()
    assignments[EndpointRole.LOCAL_HEADPHONES] = replace(
        assignments[EndpointRole.LOCAL_HEADPHONES], flow=EndpointFlow.CAPTURE
    )
    controller, outbound, inbound, *_ = bridge(tmp_path, assignments=assignments)

    with pytest.raises(ValueError, match="render"):
        controller.start()

    assert not (outbound.started or inbound.started)
    assert controller.state is BridgeState.STOPPED


def test_check_call_bridge_names_every_missing_row7_item(tmp_path) -> None:
    session = call_bridge_session()
    catalog = ready_catalog(tmp_path, session, voices=())

    availability = check_call_bridge(session, catalog, {EndpointRole.LOCAL_MICROPHONE})

    assert [describe(item, BUILTIN_REGISTRY) for item in availability.missing] == [
        "voice German",
        "voice Mandarin (Simplified)",
        "call microphone endpoint",
        "call speaker endpoint",
        "local headphones endpoint",
    ]
    assert check_call_bridge(session, ready_catalog(tmp_path / "ok", session), mapping()).available


def test_check_call_bridge_applies_only_to_call_bridge_sessions(tmp_path) -> None:
    conversation = SessionPair(
        BUILTIN_REGISTRY.pair(DE, ZH),
        UsageMode(InputKind.MICROPHONE, RoutingKind.BIDIRECTIONAL, OutputKind.SPOKEN),
    )
    with pytest.raises(UnsupportedModeError):
        check_call_bridge(conversation, ready_catalog(tmp_path, call_bridge_session()), mapping())
