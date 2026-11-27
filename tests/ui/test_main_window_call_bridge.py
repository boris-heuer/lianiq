"""MainWindow Call Bridge start (CAP-0169 WI-05, AC-09): directed lanes and fail-closed start.

The tests click the Call Bridge start control offscreen over spy adapters, synthetic
endpoints and fake endpoint streams; no audio device or model is used. The shared helpers
are in ``_call_bridge_window.py``; the restore, pair-change and stop-path tests are in
``test_main_window_call_bridge_recovery.py``.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from lianiq.call_bridge.contracts import BridgeState, EndpointRole, LaneId
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


def test_ac09_start_with_a_missing_voice_and_endpoint_starts_nothing_and_names_both(
    window,
    spies,  # noqa: F811
) -> None:
    remove_voice(window, ZH)
    assign(window, skip=EndpointRole.CALL_MICROPHONE_RENDER)
    # CAP-0166 AC-02: the readiness list names both, and Start is disabled.
    panel = window.call_bridge_panel
    assert [label.accessibleName() for label in panel.readiness_labels] == [
        "Call microphone cable — playback side: select a device",
        "Not available: missing voice Mandarin (Simplified)",
    ]
    assert not panel.start_button.isEnabled()

    window.start_call_bridge()  # a programmatic request still runs the row-7 gate

    assert bridge_notice(window) == (
        "Not available: missing voice Mandarin (Simplified), call microphone endpoint"
    )
    assert spies.constructed == []  # refused before any model loads
    assert window.call_bridge_controller is None
    assert FakeCaptureStream.instances == []  # no lane, no capture
    assert window.start_button.isEnabled()


def test_ac09_start_with_only_an_endpoint_missing_names_that_endpoint(
    window,
    spies,  # noqa: F811
) -> None:
    assign(window, skip=EndpointRole.LOCAL_HEADPHONES)
    assert not window.call_bridge_panel.start_button.isEnabled()

    window.start_call_bridge()

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
    # CAP-0166 AC-13: the turns are in the live call text, never in the Conversation.
    view = window.call_bridge_panel.text_view
    assert wait_until(lambda: len(view.turns()) == 4)
    assert [turn.splitlines()[0] for turn in view.turns()] == ["You → call", "Call → you"] * 2
    assert window.history == () and window.conversation.turns.rows == ()

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
    panel = window.call_bridge_panel  # readiness now names the lost voice
    assert "Not available: missing voice German" in [r.text for r in panel.reasons]
    assert not panel.start_button.isEnabled()


def test_ac09_local_language_setting_selects_lane_directions_and_labels(
    tmp_path,
    spies,  # noqa: F811
    monkeypatch,
) -> None:
    window = build_call_bridge_window(tmp_path, monkeypatch, local_language=ZH)
    try:
        panel = window.call_bridge_panel
        outbound, inbound = panel.paths[LaneId.OUTBOUND], panel.paths[LaneId.INBOUND]
        assert outbound.title() == "You → call · Mandarin (Simplified) → German"
        assert inbound.title() == "Call → you · German → Mandarin (Simplified)"
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

    click(window.call_bridge_panel.paths[LaneId.OUTBOUND].test_button)

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


# CAP-0167 WI-05: voice options bound at Start, row 7 and both lanes unchanged ------------

LOCKED = "Stop Call Bridge to change this voice. The running Call Bridge keeps its voice settings."


def spoken_rates(window, spies, controller) -> list[tuple[str, float]]:  # noqa: F811
    """One outbound and one inbound turn; the language and rate of each synthesis."""
    spies.synthesizer.calls.clear()
    spies.synthesizer.options.clear()
    spies.recognizer.results = [Transcript(f"turn {n}", None, 1.0, 0.1) for n in range(2)]
    outbound, inbound = FakeCaptureStream.instances[-2:]
    for capture, lane in ((outbound, controller.outbound_lane), (inbound, controller.inbound_lane)):
        capture.on_utterance(AUDIO)
        assert lane.wait_until_idle(timeout=2.0)
    languages = [language for _text, language in spies.synthesizer.calls]
    return list(zip(languages, [options.rate for options in spies.synthesizer.options]))


def test_ac17_ac18_switches_off_both_lanes_speak_with_the_options_bound_at_start(
    window,
    spies,  # noqa: F811
) -> None:
    from lianiq.tts.voice_controls import VoiceOptions

    conversation = window.conversation
    for language in (DE, ZH):  # the Conversation switches do not change Call Bridge
        conversation.voice_rows.switch(language).click()
    preferences = conversation.voice_preferences
    preferences.set_options(ZH, VoiceOptions(rate=1.25))
    assign(window)
    click(window.call_bridge_panel.start_button)
    assert wait_until(lambda: window.call_bridge_controller is not None)
    for voice_rows in (conversation.voice_rows, window.settings.voice_rows):
        for language in (DE, ZH):
            assert not voice_rows.options_button(language).isEnabled()
            assert voice_rows.options_button(language).toolTip() == LOCKED
    usage = window.usage_tracker.current
    assert usage.voices == frozenset({DE, ZH})  # both lane voices are protected

    preferences.set_options(ZH, VoiceOptions(rate=1.5))  # applies at the next Start only
    assert spoken_rates(window, spies, window.call_bridge_controller) == [(ZH, 1.25), (DE, 1.0)]

    click(window.call_bridge_panel.stop_button)
    assert conversation.voice_rows.options_button(ZH).isEnabled()
    assert conversation.voice_rows.options_button(ZH).toolTip() == ""
    click(window.call_bridge_panel.start_button)
    assert wait_until(lambda: window.call_bridge_controller is not None)
    assert spoken_rates(window, spies, window.call_bridge_controller) == [(ZH, 1.5), (DE, 1.0)]
