"""MainWindow Call Bridge lane status, stop and device loss (CAP-0166 WI-03).

AC-07, AC-08 (the three #24 contradictions as regression tests), AC-09, AC-10, AC-11, the
echo pause of AC-12 in the UI and AC-14 (cleared at Start), clicked offscreen over spy
adapters, synthetic endpoints and fake endpoint streams; no audio device or model is used.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from lianiq.call_bridge.contracts import BridgeEvent, BridgeEventKind, EndpointRole, LaneId
from lianiq.call_bridge.route_tests import RouteTestState
from lianiq.domain import Transcript
from tests._spy_window import spies  # noqa: F401
from tests.call_bridge.support import mapping
from tests.ui._call_bridge_window import (
    AUDIO,
    FakeCaptureStream,
    assign,
    bridge_notice,
    call_bridge_window,  # noqa: F401
    click,
    wait_until,
)
from tests.ui.test_main_window_call_bridge_setup import HeldPlayback

OUT, IN = LaneId.OUTBOUND, LaneId.INBOUND
ACTIVITY = BridgeEventKind.ACTIVITY


def statuses(window) -> tuple[str, str]:
    paths = window.call_bridge_panel.paths
    return paths[OUT].status_label.text(), paths[IN].status_label.text()


def emit(window, lane, kind, category, generation=None) -> None:
    if generation is None:
        generation = window.call_bridge.lane_status.generation
    event = BridgeEvent(lane, kind, category, "", None, generation)
    window.bridge.call_bridge_event.emit(event)


def start(window) -> None:
    click(window.call_bridge_panel.start_button)
    assert wait_until(lambda: window.call_bridge_controller is not None)


def test_ac07_each_path_shows_its_own_lane_activity(window) -> None:
    assign(window)
    assert statuses(window) == ("Stopped", "Stopped")
    start(window)
    assert statuses(window) == ("Listening", "Listening")
    emit(window, OUT, ACTIVITY, "translating")
    assert statuses(window) == ("Translating…", "Listening")
    emit(window, IN, ACTIVITY, "speaking")
    assert statuses(window) == ("Translating…", "Speaking")
    emit(window, IN, BridgeEventKind.ERROR, "recognition_failure")
    assert statuses(window) == ("Translating…", "Muted — recognition_failure")
    status = window.call_bridge_panel.paths[IN].status_label
    assert status.accessibleName() == "Lane status: Muted — recognition_failure"
    click(window.call_bridge_panel.stop_button)
    assert statuses(window) == ("Stopped", "Stopped")


def test_ac08_a_stale_generation_event_after_a_restart_changes_nothing(window) -> None:
    """#24 contradiction 1: a late event of the previous start."""
    assign(window)
    start(window)
    old = window.call_bridge.lane_status.generation
    click(window.call_bridge_panel.stop_button)
    start(window)
    assert window.call_bridge_controller.generation == window.session_owner.generation != old
    emit(window, IN, ACTIVITY, "speaking", generation=old)
    emit(window, None, BridgeEventKind.STATE, "stopped", generation=old)
    assert statuses(window) == ("Listening", "Listening")


def test_ac08_a_route_test_interleaved_with_controller_events_keeps_the_lanes(window) -> None:
    """#24 contradictions 2 and 3: a route test is never a lane state, never *Running*."""
    assign(window)
    held = HeldPlayback()
    window.call_bridge.play_route_test = held
    panel = window.call_bridge_panel
    click(panel.paths[OUT].test_button)
    assert wait_until(lambda: held.endpoints)
    emit(window, None, BridgeEventKind.STATE, "running", generation=0)
    emit(window, OUT, ACTIVITY, "speaking", generation=0)
    assert statuses(window) == ("Stopped", "Stopped")
    # WI-02 advisory: Start stays disabled while a test plays or awaits its answer.
    assert not panel.start_button.isEnabled()
    assert "Finish or cancel the route test first" in [r.text for r in panel.reasons]
    held.release.set()
    route_tests = window.call_bridge.route_tests
    assert wait_until(lambda: route_tests.state(OUT) is RouteTestState.AWAITING_ANSWER)
    assert not panel.start_button.isEnabled()
    window.call_bridge.start_call_bridge()  # a programmatic Start is refused too
    assert window.call_bridge_controller is None and not window.call_bridge.starting
    click(panel.paths[OUT].yes_button)
    assert panel.paths[OUT].test_status.text() == "Test passed"
    assert statuses(window) == ("Stopped", "Stopped")
    assert panel.start_button.isEnabled()
    start(window)
    assert statuses(window) == ("Listening", "Listening")
    assert not any("Running" in text for text in statuses(window))


def test_ac09_ac10_running_locks_the_controls_and_f9_unlocks_them_anywhere(window) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from lianiq.ui.shell.workspaces import WorkspaceId

    assign(window)
    start(window)
    panel = window.call_bridge_panel
    controller = window.call_bridge_controller
    controls = [*panel.endpoint_combos.values(), *(b.test_button for b in panel.paths.values())]
    assert not any(widget.isEnabled() for widget in controls)
    assert not window.pair_combo.isEnabled()
    window.show_workspace(WorkspaceId.CONVERSATION)

    QTest.keyClick(window, Qt.Key.Key_F9)

    assert window.call_bridge_controller is None
    assert not controller.outbound_lane.running and not controller.inbound_lane.running
    assert not any(capture.running for capture in FakeCaptureStream.instances)
    assert statuses(window) == ("Stopped", "Stopped")
    assert all(widget.isEnabled() for widget in controls)
    assert window.pair_combo.isEnabled()


def test_ac11_a_lost_endpoint_mutes_only_its_lane_and_recovers_by_identity(
    window, monkeypatch
) -> None:
    from lianiq.audio.endpoints import EndpointInventory
    from lianiq.ui.workspaces import call_bridge as module

    assign(window)
    start(window)
    outbound_capture, inbound_capture = FakeCaptureStream.instances
    endpoints = mapping()
    headphones = endpoints.pop(EndpointRole.LOCAL_HEADPHONES)
    lost = EndpointInventory(endpoints.values())
    monkeypatch.setattr(module, "list_audio_endpoints", lambda: lost)
    window.call_bridge._reconcile_call_bridge_endpoints()

    assert statuses(window) == ("Listening", "Device lost — Device local_headphones")
    assert bridge_notice(window) == (
        "Call Bridge · Call → you lane failed closed: Device lost — Device local_headphones"
    )
    assert outbound_capture.running and not inbound_capture.running  # the other lane goes on
    assert len(FakeCaptureStream.instances) == 2  # no default device was opened
    shown = []
    status = window.call_bridge_panel.paths[IN].status_label
    monkeypatch.setattr(status, "setText", shown.append)  # the label keeps its old text
    restored = EndpointInventory((*endpoints.values(), headphones))
    monkeypatch.setattr(module, "list_audio_endpoints", lambda: restored)
    window.call_bridge._reconcile_call_bridge_endpoints()

    assert list(dict.fromkeys(shown)) == ["Reconnecting…", "Listening"]
    assert inbound_capture.running
    assignments = window.call_bridge_controller.assignments
    assert assignments[EndpointRole.LOCAL_HEADPHONES].endpoint_id == headphones.endpoint_id


def test_ac12_outbound_reads_paused_while_you_hear_the_translation(window) -> None:
    assign(window)
    start(window)
    controller = window.call_bridge_controller
    outbound_capture = FakeCaptureStream.instances[0]
    guard = controller.inbound_lane.echo_guard
    assert guard is controller.outbound_lane.echo_guard
    guard.playback_started()
    assert outbound_capture.muted() is True
    assert statuses(window) == ("Paused while you hear the translation", "Listening")
    guard.playback_finished()  # the test window sets guard_tail_ms to 0
    assert outbound_capture.muted() is False
    assert statuses(window) == ("Listening", "Listening")


def test_ac14_the_live_text_stays_after_stop_and_clears_at_start(window, spies) -> None:  # noqa: F811
    assign(window)
    start(window)
    spies.recognizer.results = [Transcript("Guten Tag", None, 1.0, 0.1)]
    FakeCaptureStream.instances[0].on_utterance(AUDIO)
    view = window.call_bridge_panel.text_view
    assert wait_until(lambda: len(view.turns()) == 1)
    click(window.call_bridge_panel.stop_button)
    assert len(view.turns()) == 1
    start(window)
    assert view.turns() == [] and view.empty_label.text() == "Nothing translated yet."
