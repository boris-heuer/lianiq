"""CAP-0166 AC-07, AC-08: per-lane status from generation-stamped bridge events."""

from __future__ import annotations

from lianiq.call_bridge.contracts import BridgeEvent, BridgeEventKind, LaneId
from lianiq.call_bridge.lane_status import LaneActivity, LaneStatus, LaneStatusBook

OUT, IN = LaneId.OUTBOUND, LaneId.INBOUND
ACTIVITY, STATE, ENDPOINT = (
    BridgeEventKind.ACTIVITY,
    BridgeEventKind.STATE,
    BridgeEventKind.ENDPOINT,
)


def event(lane, kind, category, generation=1, message=""):
    return BridgeEvent(lane, kind, category, message, generation=generation)


def activities(book: LaneStatusBook) -> tuple[LaneActivity, LaneActivity]:
    return book.statuses[OUT].activity, book.statuses[IN].activity


def test_each_lane_shows_its_own_activity() -> None:
    book = LaneStatusBook()
    assert activities(book) == (LaneActivity.STOPPED, LaneActivity.STOPPED)
    book.reset(1)
    assert activities(book) == (LaneActivity.STARTING, LaneActivity.STARTING)
    assert book.apply(event(None, STATE, "running")) is None
    assert activities(book) == (LaneActivity.LISTENING, LaneActivity.LISTENING)
    assert book.apply(event(OUT, ACTIVITY, "translating")) == LaneStatus(
        OUT, LaneActivity.TRANSLATING, ""
    )
    book.apply(event(IN, ACTIVITY, "speaking"))
    assert activities(book) == (LaneActivity.TRANSLATING, LaneActivity.SPEAKING)
    book.apply(event(OUT, ACTIVITY, "echo_paused"))
    book.apply(event(IN, BridgeEventKind.ERROR, "stt_failure"))
    assert book.statuses[OUT].activity is LaneActivity.ECHO_PAUSED
    assert book.statuses[IN] == LaneStatus(IN, LaneActivity.MUTED, "stt_failure")


def test_device_loss_and_recovery_name_the_device() -> None:
    book = LaneStatusBook()
    book.reset(1)
    book.apply(event(None, STATE, "running"))
    lost = book.apply(event(IN, ENDPOINT, "endpoint_lost"), detail="Headset Earphone")
    assert lost == LaneStatus(IN, LaneActivity.DEVICE_LOST, "Headset Earphone")
    # A late activity of the lost lane does not hide the loss; the other lane continues.
    book.apply(event(IN, ACTIVITY, "listening"))
    book.apply(event(OUT, ACTIVITY, "speaking"))
    assert activities(book) == (LaneActivity.SPEAKING, LaneActivity.DEVICE_LOST)
    book.apply(event(IN, ENDPOINT, "endpoint_reconnecting"))
    assert book.statuses[IN].activity is LaneActivity.RECONNECTING
    book.apply(event(IN, ENDPOINT, "endpoint_recovered"))
    assert book.statuses[IN].activity is LaneActivity.LISTENING


def test_stop_sets_both_lanes_stopped() -> None:
    book = LaneStatusBook()
    book.reset(3)
    book.apply(event(OUT, ACTIVITY, "speaking", generation=3))
    book.apply(event(None, STATE, "stopped", generation=3))
    assert activities(book) == (LaneActivity.STOPPED, LaneActivity.STOPPED)
    # A playback that ends after Stop does not revive the lane.
    book.apply(event(OUT, ACTIVITY, "listening", generation=3))
    assert book.statuses[OUT].activity is LaneActivity.STOPPED


def test_regression_24_stale_generation_event_is_ignored() -> None:
    book = LaneStatusBook()
    book.reset(2)
    assert book.apply(event(OUT, ACTIVITY, "speaking", generation=1)) is None
    assert book.apply(event(IN, ENDPOINT, "endpoint_lost", generation=1)) is None
    assert activities(book) == (LaneActivity.STARTING, LaneActivity.STARTING)


def test_regression_24_route_test_result_never_becomes_a_lane_activity() -> None:
    book = LaneStatusBook()
    for generation in (0, book.generation):
        assert book.apply(event(None, ENDPOINT, "route_test_passed", generation)) is None
        assert book.apply(event(None, BridgeEventKind.ERROR, "OSError", generation)) is None
    assert activities(book) == (LaneActivity.STOPPED, LaneActivity.STOPPED)


def test_regression_24_state_events_of_an_earlier_start_are_ignored() -> None:
    book = LaneStatusBook()
    book.reset(5)
    book.apply(event(None, STATE, "running", generation=5))
    assert book.apply(event(None, STATE, "stopped", generation=4)) is None
    assert activities(book) == (LaneActivity.LISTENING, LaneActivity.LISTENING)
    assert book.generation == 5
