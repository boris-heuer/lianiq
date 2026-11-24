"""CAP-0166 AC-07, AC-08, AC-12: lane activity events, generation stamps and echo hooks."""

from __future__ import annotations

import threading

from lianiq.call_bridge.contracts import BridgeEventKind, CallBridgeLanes, LaneId
from lianiq.call_bridge.controller import FullDuplexBridgeController
from lianiq.call_bridge.echo_guard import EchoGuard
from lianiq.call_bridge.inference_scheduler import InferenceScheduler
from lianiq.call_bridge.translation_lane import TranslationLane
from tests.call_bridge.support import call_bridge_session, mapping, ready_catalog
from tests.call_bridge.test_full_duplex_controller import FakeCapture, FakeLane
from tests.call_bridge.test_translation_lane import (
    DE_ZH,
    ZH_DE,
    Recognizer,
    Synthesizer,
    Translator,
    utterance,
)


class Clock:
    now = 0.0

    def __call__(self) -> float:
        return self.now


def lane(lane_id, edge, events, playback=lambda _path: None, guard=None) -> TranslationLane:
    return TranslationLane(
        lane_id,
        edge,
        Recognizer(),
        Translator(),
        Synthesizer(),
        playback,
        InferenceScheduler(max_concurrent=1),
        on_event=events.append,
        echo_guard=guard,
    )


def activity(events) -> list[str]:
    return [e.category for e in events if e.kind is BridgeEventKind.ACTIVITY]


def test_inbound_lane_reports_activity_and_guards_its_playback() -> None:
    events, muted_during_playback = [], []
    guard = EchoGuard(guard_tail_ms=0, clock=Clock())
    inbound = lane(
        LaneId.INBOUND,
        ZH_DE,
        events,
        playback=lambda _path: muted_during_playback.append(guard.outbound_muted()),
        guard=guard,
    )
    inbound.generation = 7
    inbound.start()
    inbound.submit(utterance(1))
    assert inbound.wait_until_idle(timeout=1.0)
    inbound.stop(timeout=1.0)
    assert activity(events) == ["translating", "speaking", "listening"]
    assert {e.generation for e in events} == {7}
    assert muted_during_playback == [True]
    assert not guard.outbound_muted()


def test_failed_playback_still_releases_the_echo_guard() -> None:
    def fail(_path):
        raise OSError("device gone")

    guard = EchoGuard(guard_tail_ms=0, clock=Clock())
    inbound = lane(LaneId.INBOUND, ZH_DE, [], playback=fail, guard=guard)
    inbound.start()
    inbound.submit(utterance(1))
    assert inbound.wait_until_idle(timeout=1.0)
    inbound.stop(timeout=1.0)
    assert not guard.outbound_muted()


def test_outbound_capture_hook_pauses_once_and_discards_utterances() -> None:
    events, clock = [], Clock()
    guard = EchoGuard(guard_tail_ms=300, clock=clock)
    outbound = lane(LaneId.OUTBOUND, DE_ZH, events, guard=guard)
    assert not outbound.echo_muted()
    guard.playback_started()
    assert outbound.echo_muted() and outbound.echo_muted()  # paused once, not per block
    outbound.start()
    assert outbound.submit(utterance(1)) is False  # muted audio never becomes a turn
    guard.playback_finished()
    clock.now = 0.2
    assert outbound.echo_muted()
    clock.now = 0.4
    assert not outbound.echo_muted()
    outbound.stop(timeout=1.0)
    assert activity(events) == ["echo_paused", "listening"]
    assert not any(e.kind is BridgeEventKind.DROPPED for e in events)


def test_lane_without_guard_never_mutes() -> None:
    outbound = lane(LaneId.OUTBOUND, DE_ZH, [])
    assert not outbound.echo_muted()


def test_controller_stamps_its_start_generation_on_every_event(tmp_path) -> None:
    session = call_bridge_session()
    lanes = CallBridgeLanes.from_session(session)
    outbound, inbound = FakeLane(lanes.outbound), FakeLane(lanes.inbound)
    events = []
    controller = FullDuplexBridgeController(
        mapping(),
        outbound,
        inbound,
        FakeCapture(),
        FakeCapture(),
        on_event=events.append,
        session=session,
        catalog=ready_catalog(tmp_path, session),
    )
    controller.start()
    assert controller.generation == 1 and outbound.generation == inbound.generation == 1
    controller.stop()
    controller.start(generation=9)
    assert outbound.generation == 9
    controller.endpoint_lost(next(iter(controller.assignments)))
    assert [e.generation for e in events[:4]] == [1, 1, 1, 1]
    assert {e.generation for e in events[4:]} == {9}


def test_activity_events_are_thread_safe_under_concurrent_hooks() -> None:
    events = []
    guard = EchoGuard(guard_tail_ms=0, clock=Clock())
    outbound = lane(LaneId.OUTBOUND, DE_ZH, events, guard=guard)
    guard.playback_started()
    threads = [threading.Thread(target=outbound.echo_muted) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert activity(events) == ["echo_paused"]
