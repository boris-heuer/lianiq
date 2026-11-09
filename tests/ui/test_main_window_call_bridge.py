"""MainWindow Call Bridge start (CAP-0169 WI-05, AC-09): directed lanes and fail-closed start.

The tests click the Call Bridge start control offscreen over spy adapters, synthetic
endpoints and fake endpoint streams; no audio device or model is used. The shared helpers
are in ``_call_bridge_window.py``; the restore, pair-change and stop-path tests are in
``test_main_window_call_bridge_recovery.py``.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from lianiq.call_bridge.contracts import BridgeState, EndpointRole
from lianiq.domain import Transcript
from tests._spy_window import spies  # noqa: F401
from tests.call_bridge.support import DE, ZH
from tests.ui._call_bridge_window import (
    AUDIO,
    FakeCaptureStream,
    FakePlaybackStream,
    assign,
    bridge_notice,
    build_call_bridge_window,
    call_bridge_window,  # noqa: F401
    click,
    remove_voice,
    wait_until,
)


def test_ac09_click_start_with_a_missing_voice_and_endpoint_starts_nothing_and_names_both(
    window,
    spies,  # noqa: F811
) -> None:
    remove_voice(window, ZH)
    assign(window, skip=EndpointRole.CALL_MICROPHONE_RENDER)

    click(window.call_bridge_panel.start_button)

    assert bridge_notice(window) == (
        "Not available: missing voice Mandarin (Simplified), call microphone endpoint"
    )
    assert spies.constructed == []  # refused before any model loads
    assert window.call_bridge_controller is None
    assert FakeCaptureStream.instances == []  # no lane, no capture
    assert window.call_bridge_panel.start_button.isEnabled()
    assert window.start_button.isEnabled()


def test_ac09_click_start_with_only_an_endpoint_missing_names_that_endpoint(
    window,
    spies,  # noqa: F811
) -> None:
    assign(window, skip=EndpointRole.LOCAL_HEADPHONES)

    click(window.call_bridge_panel.start_button)

    assert bridge_notice(window) == "Not available: missing local headphones endpoint"
    assert spies.constructed == []
    assert window.call_bridge_controller is None


def test_ac09_click_start_runs_local_to_remote_and_remote_to_local_for_the_session(
    window,
    spies,  # noqa: F811
) -> None:
    assign(window)

    click(window.call_bridge_panel.start_button)
    assert wait_until(lambda: window.call_bridge_controller is not None)
    controller = window.call_bridge_controller
    assert controller.state is BridgeState.RUNNING
    assert controller.outbound_lane.edge.key == "de>zh-Hans"
    assert controller.inbound_lane.edge.key == "zh-Hans>de"
    assert sorted(spies.recognizer.warmed_languages) == ["de", "zh-Hans"]
    assert sorted(spies.translator.warmed_edges) == ["de>zh-Hans", "zh-Hans>de"]

    outbound_capture, inbound_capture = FakeCaptureStream.instances
    spies.recognizer.results = [Transcript(f"turn {n}", None, 1.0, 0.1) for n in range(4)]
    for capture in (outbound_capture, inbound_capture, outbound_capture, inbound_capture):
        capture.on_utterance(AUDIO)
        lane = controller.outbound_lane if capture is outbound_capture else controller.inbound_lane
        assert lane.wait_until_idle(timeout=2.0)

    assert [edge for _text, edge, _context in spies.translator.calls] == [
        "de>zh-Hans",
        "zh-Hans>de",
        "de>zh-Hans",
        "zh-Hans>de",
    ]
    assert spies.recognizer.calls == ["de", "zh-Hans", "de", "zh-Hans"]
    assert FakePlaybackStream.played == [
        ("id-call_microphone_render", "synthetic-zh-Hans.wav"),
        ("id-local_headphones", "synthetic-de.wav"),
        ("id-call_microphone_render", "synthetic-zh-Hans.wav"),
        ("id-local_headphones", "synthetic-de.wav"),
    ]
    assert wait_until(lambda: len(window.history) == 4)
    assert [(r.source_language, r.target_language) for r in window.history] == [
        (DE, ZH),
        (ZH, DE),
        (DE, ZH),
        (ZH, DE),
    ]

    click(window.call_bridge_panel.stop_button)
    assert window.call_bridge_controller is None
    assert not controller.outbound_lane.running and not controller.inbound_lane.running


def test_ac09_voice_lost_while_models_load_fails_closed_at_controller_start(
    window,
    spies,  # noqa: F811
) -> None:
    assign(window)
    spies.release_warm_up.clear()  # hold Start while its models load

    click(window.call_bridge_panel.start_button)
    remove_voice(window, DE)
    spies.release_warm_up.set()

    assert wait_until(lambda: bridge_notice(window) == "Not available: missing voice German")
    assert window.call_bridge_controller is None
    assert not any(capture.running for capture in FakeCaptureStream.instances)
    assert FakePlaybackStream.played == []
    assert window.call_bridge_panel.start_button.isEnabled()


def test_ac09_local_language_setting_selects_lane_directions_and_labels(
    tmp_path,
    spies,  # noqa: F811
    monkeypatch,
) -> None:
    window = build_call_bridge_window(tmp_path, monkeypatch, local_language=ZH)
    try:
        panel = window.call_bridge_panel
        assert (
            panel.role_label_widgets[EndpointRole.LOCAL_MICROPHONE].text()
            == "Local microphone · Mandarin (Simplified) source"
        )
        assert panel.outbound_test_button.text() == "Test German → call mic"
        assert panel.inbound_test_button.text() == "Test Mandarin (Simplified) → headphones"
        assign(window)

        click(panel.start_button)
        assert wait_until(lambda: window.call_bridge_controller is not None)

        controller = window.call_bridge_controller
        assert controller.outbound_lane.edge.key == "zh-Hans>de"
        assert controller.inbound_lane.edge.key == "de>zh-Hans"
    finally:
        window.stop_call_bridge()
        window.close()


def test_route_test_uses_the_remote_language_for_the_call_mic(window, spies) -> None:  # noqa: F811
    assign(window)

    click(window.call_bridge_panel.outbound_test_button)

    assert wait_until(lambda: FakePlaybackStream.played)
    assert FakePlaybackStream.played == [("id-call_microphone_render", "synthetic-zh-Hans.wav")]
    assert spies.synthesizer.calls == [("通话麦克风测试。", ZH)]


def test_ac09_a_refused_call_bridge_start_leaves_a_running_conversation_alone(
    window,
    spies,  # noqa: F811
) -> None:
    click(window.start_button)
    assert wait_until(lambda: window.capture.running)
    assign(window, skip=EndpointRole.CALL_SPEAKER_CAPTURE)
    # CAP-0168 AC-07: while the conversation runs, the panel's Start is disabled; the
    # programmatic request is still refused and names the missing endpoint first.
    assert not window.call_bridge_panel.start_button.isEnabled()

    window.start_call_bridge()

    assert bridge_notice(window) == "Not available: missing call speaker endpoint"
    assert window.capture.running and window.session_controller.running
    assert window.call_bridge_controller is None
    window.stop_listening()
