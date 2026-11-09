"""Notices with the Call Bridge (CAP-0168 WI-03; spec §2.3.4, AC-24, AC-25): UI tests.

AC-24: a ``BridgeEvent`` error and a capture fault are exactly one Call Bridge notice whose
source names the lane and the language that lane listens to. AC-25: **Retry** runs the same
gate as **Start**, so it is refused with ``SESSION_BUSY`` while the Call Bridge holds the
session, and a later Retry starts a new session generation through the owner.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from lianiq.call_bridge.contracts import BridgeEvent, BridgeEventKind, EndpointRole, LaneId
from lianiq.ui import notice_catalog as catalog
from lianiq.ui.notices import Severity
from lianiq.ui.shell.session_owner import SessionState
from lianiq.ui.shell.workspaces import WorkspaceId
from tests._spy_window import spies  # noqa: F401
from tests.ui._call_bridge_window import assign, build_call_bridge_window
from tests.ui._language_helpers import wait_until
from tests.ui.test_main_window_session import click

CONVERSATION, CALL_BRIDGE = WorkspaceId.CONVERSATION, WorkspaceId.CALL_BRIDGE


@pytest.fixture
def window(tmp_path, spies, monkeypatch):  # noqa: F811
    window = build_call_bridge_window(tmp_path, monkeypatch)  # local German, remote Mandarin
    yield window
    window.stop_call_bridge()
    window.stop_listening()
    window.close()


def bridge_notices(window):
    return window.notices.live(CALL_BRIDGE)


# AC-24: Call Bridge cases -----------------------------------------------------------------


def test_ac24_a_bridge_error_is_one_notice_naming_the_lane_and_its_language(window) -> None:
    event = BridgeEvent(
        LaneId.INBOUND, BridgeEventKind.ERROR, "recognition_failure", "inference_failed", 1
    )
    window.bridge.call_bridge_event.emit(event)
    window.bridge.call_bridge_event.emit(event)  # a repeat updates the one notice

    (notice,) = bridge_notices(window)
    assert notice.title == "Call Bridge inbound lane failed closed: recognition_failure"
    # The inbound lane listens to the remote language (Mandarin), not its German target.
    assert notice.source == "Call Bridge · inbound · Mandarin (Simplified)"
    assert notice.continues == "This lane is muted; the other lane continues."
    assert notice.repeats == 1 and notice.severity is Severity.WARNING
    banner = window.banners[CALL_BRIDGE]
    assert banner.title_label.text() == (
        "Warning: Call Bridge inbound lane failed closed: recognition_failure (2×)"
    )
    assert window.notices.live(CONVERSATION) == ()


def test_ac24_the_outbound_lane_names_the_local_language(window) -> None:
    window.bridge.call_bridge_event.emit(
        BridgeEvent(LaneId.OUTBOUND, BridgeEventKind.ERROR, "playback_failure", "render", 2)
    )
    (notice,) = bridge_notices(window)
    assert notice.source == "Call Bridge · outbound · German"
    assert notice.key == catalog.bridge_failed_key("outbound")


def test_ac24_a_capture_fault_is_one_notice_naming_the_lane_and_its_language(window) -> None:
    window.bridge.call_bridge_capture_fault.emit(EndpointRole.CALL_SPEAKER_CAPTURE, "stream error")

    (notice,) = bridge_notices(window)
    assert notice.title == "Call Bridge capture muted: stream error"
    assert notice.source == "Call Bridge · inbound · Mandarin (Simplified)"
    assert "lane is muted" in notice.continues

    window.bridge.call_bridge_capture_fault.emit(EndpointRole.LOCAL_MICROPHONE, "stream error")
    (notice,) = bridge_notices(window)  # the same failure kind: still one notice
    assert notice.source == "Call Bridge · outbound · German"


def test_ac24_a_dropped_turn_is_an_info_notice(window) -> None:
    window.bridge.call_bridge_event.emit(
        BridgeEvent(LaneId.OUTBOUND, BridgeEventKind.DROPPED, "stale_turn", "too old", 3)
    )
    (notice,) = bridge_notices(window)
    assert notice.title == "Call Bridge dropped stale work: stale_turn"
    assert notice.severity is Severity.INFO
    assert notice.source == "Call Bridge · outbound · German"


# AC-25: Retry runs the Start gate (wave-1 B2) ---------------------------------------------


def test_ac25_retry_is_refused_while_the_call_bridge_holds_the_session(window, spies) -> None:  # noqa: F811
    spies.failing_warm_up_calls = {1}
    click(window.start_button)  # the conversation's models fail: a blocking notice with Retry
    assert wait_until(lambda: window.state_label.text() == "Model error")
    retry = next(
        b for b in window.banners[CONVERSATION].action_buttons if b.accessibleName() == "Retry"
    )

    assign(window)
    click(window.call_bridge_panel.start_button)
    assert wait_until(lambda: window.call_bridge_controller is not None)
    bridge_generation = window.session_owner.generation

    click(retry)  # the gate refuses: the Call Bridge holds the session

    busy = window.notices.get(catalog.busy_key(CONVERSATION))
    assert busy is not None and busy.severity is Severity.INFO
    assert busy.title == "Stop the Call Bridge session first"
    assert not window.capture.running and not window.conversation.starting
    assert window.session_owner.active is CALL_BRIDGE
    assert window.session_owner.generation == bridge_generation

    window.stop_call_bridge()
    assert window.notices.get(catalog.busy_key(CONVERSATION)) is None
    click(retry)  # now the gate passes: a new owner generation, running

    assert wait_until(lambda: window.capture.running)
    assert window.session_owner.state is SessionState.RUNNING
    assert window.session_owner.active is CONVERSATION
    assert window.session_owner.generation == bridge_generation + 1
    assert window.notices.live(CONVERSATION) == ()


def test_ac25_mode_unavailable_retry_is_refused_while_the_call_bridge_runs(window) -> None:
    from tests._fake_devices import SPEAKERS

    devices = list(window.devices)
    window.devices = [SPEAKERS]  # no microphone
    window.start_listening()  # the mode-unavailable notice built by show_unavailable
    notice = window.notices.get(catalog.unavailable_key(CONVERSATION))
    assert notice is not None and [a.label for a in notice.actions] == ["Retry"]
    retry = next(
        b for b in window.banners[CONVERSATION].action_buttons if b.accessibleName() == "Retry"
    )
    window.devices = devices  # the microphone is back; only the session lock remains

    assign(window)
    click(window.call_bridge_panel.start_button)
    assert wait_until(lambda: window.call_bridge_controller is not None)
    bridge_generation = window.session_owner.generation

    click(retry)  # the Start gate refuses: the Call Bridge holds the session

    busy = window.notices.get(catalog.busy_key(CONVERSATION))
    assert busy is not None and busy.severity is Severity.INFO
    assert busy.title == "Stop the Call Bridge session first"
    assert not window.capture.running and not window.conversation.starting
    assert window.session_owner.active is CALL_BRIDGE
    assert window.session_owner.generation == bridge_generation
