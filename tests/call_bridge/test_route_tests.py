"""CAP-0166 AC-06: a route-test result belongs to one path and its fingerprint."""

from __future__ import annotations

from lianiq.call_bridge.contracts import EndpointRole, LaneId
from lianiq.call_bridge.lane_status import LaneActivity
from lianiq.call_bridge.route_tests import RouteTestBook, RouteTestState
from lianiq.languages import BUILTIN_REGISTRY
from tests.call_bridge.support import DE, ZH

OUT, IN = LaneId.OUTBOUND, LaneId.INBOUND
PAIR = BUILTIN_REGISTRY.pair(DE, ZH)
IDS = {role: f"id-{role.value}" for role in EndpointRole}


def passed_book() -> RouteTestBook:
    book = RouteTestBook()
    book.update(IDS, PAIR, DE)
    book.set(OUT, RouteTestState.PASSED)
    book.set(IN, RouteTestState.FAILED, "speaker setting")
    return book


def test_a_device_change_resets_only_its_path() -> None:
    book = passed_book()
    changed = book.update({**IDS, EndpointRole.LOCAL_HEADPHONES: "other"}, PAIR, DE)
    assert changed == frozenset({IN})
    assert book.state(OUT) is RouteTestState.PASSED
    assert book.state(IN) is RouteTestState.NOT_TESTED
    assert book.detail(IN) == ""


def test_pair_or_local_language_change_resets_both_paths() -> None:
    book = passed_book()
    assert book.update(IDS, PAIR, DE) == frozenset()  # unchanged fingerprint
    assert book.update(IDS, PAIR, ZH) == frozenset({OUT, IN})
    assert {book.state(OUT), book.state(IN)} == {RouteTestState.NOT_TESTED}


def test_a_result_is_never_a_lane_activity() -> None:
    values = {state.value for state in RouteTestState}
    assert values.isdisjoint(activity.value for activity in LaneActivity)
    assert "running" not in values
