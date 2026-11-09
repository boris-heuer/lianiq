"""MainWindow Call Bridge start (CAP-0169 WI-05, AC-09): directed lanes and fail-closed start.

The tests click the Call Bridge start control offscreen over spy adapters, synthetic
endpoints and fake endpoint streams; no audio device or model is used.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import ClassVar

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from lianiq.call_bridge.contracts import BridgeState, EndpointRole
from lianiq.domain import AudioUtterance, Transcript
from tests.call_bridge.support import DE, ZH, mapping
from tests.test_requirement_scoped_loading import (  # noqa: F401
    config_without_stt_and_voices,
    provision_stt_and_voices,
    spies,
)

AUDIO = AudioUtterance(np.zeros(1_600, dtype=np.float32), 16_000)


def bridge_notice(window) -> str:
    """The title of the Call Bridge workspace's top notice (CAP-0168 WI-03)."""
    from lianiq.ui.shell.workspaces import WorkspaceId

    notice = window.notices.top(WorkspaceId.CALL_BRIDGE)
    return "" if notice is None else notice.title


def wait_until(condition, timeout_ms: int = 3_000) -> bool:
    from PySide6.QtTest import QTest

    waited = 0
    while not condition() and waited < timeout_ms:
        QTest.qWait(10)
        waited += 10
    return condition()


def click(widget) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    QTest.mouseClick(widget, Qt.MouseButton.LeftButton)


class FakeCaptureStream:
    instances: ClassVar[list[FakeCaptureStream]] = []

    def __init__(self, endpoint, _config, on_utterance, on_level=None, on_error=None) -> None:
        self.endpoint = endpoint
        self.on_utterance = on_utterance
        self.running = False
        FakeCaptureStream.instances.append(self)

    def start(self) -> None:
        self.running = True

    def stop(self) -> None:
        self.running = False

    def rebind(self, endpoint) -> None:
        self.endpoint = endpoint


class FakePlaybackStream:
    played: ClassVar[list[tuple[str, str]]] = []

    def __init__(self, endpoint) -> None:
        self.endpoint = endpoint

    def play(self, path) -> None:
        FakePlaybackStream.played.append((self.endpoint.endpoint_id, Path(path).name))

    def rebind(self, endpoint) -> None:
        self.endpoint = endpoint


def build_call_bridge_window(
    tmp_path, monkeypatch, *, local_language: str = DE, registry=None, configure=None
):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    import lianiq.ui.main_window as main_window_module
    import lianiq.ui.workspaces.call_bridge as call_bridge_module
    import lianiq.ui.workspaces.conversation as conversation_module
    from lianiq.app import build_pipeline
    from lianiq.audio.devices import AudioDevice
    from lianiq.audio.endpoints import EndpointInventory
    from lianiq.languages import BUILTIN_REGISTRY, ReadinessProbe

    QApplication.instance() or QApplication([])
    inventory = EndpointInventory(mapping().values())
    # One microphone and one speaker, as in build_window(), so conversation modes are ready.
    devices = [AudioDevice(0, "Test microphone", 1, 0), AudioDevice(1, "Test speakers", 0, 2)]
    monkeypatch.setattr(conversation_module, "list_audio_devices", lambda: list(devices))
    monkeypatch.setattr(call_bridge_module, "list_audio_endpoints", lambda: inventory)
    monkeypatch.setattr(call_bridge_module, "EndpointCaptureStream", FakeCaptureStream)
    monkeypatch.setattr(call_bridge_module, "EndpointPlaybackStream", FakePlaybackStream)
    # No real microphone: conversation capture is faked as in build_window().
    capture = conversation_module.MicrophoneCapture
    monkeypatch.setattr(capture, "start", lambda self: setattr(self, "_stream", object()))
    monkeypatch.setattr(capture, "stop", lambda self: setattr(self, "_stream", None))
    FakeCaptureStream.instances = []
    FakePlaybackStream.played = []
    config = config_without_stt_and_voices(tmp_path)
    provision_stt_and_voices(tmp_path, config)
    config.call_bridge.local_language = local_language
    if configure is not None:
        configure(config, tmp_path)
    pipeline = build_pipeline(config, registry or BUILTIN_REGISTRY, probe=ReadinessProbe(tmp_path))
    window = main_window_module.MainWindow(config, pipeline, persist_settings=False)
    window.call_bridge_panel.enabled_checkbox.setChecked(True)
    window.show()
    return window


def assign(window, *, skip: EndpointRole | None = None) -> None:
    for role, endpoint in mapping().items():
        if role is skip:
            continue
        combo = window.call_bridge_panel.endpoint_combos[role]
        combo.setCurrentIndex(combo.findData(endpoint.endpoint_id))


@pytest.fixture
def window(tmp_path, spies, monkeypatch):  # noqa: F811
    window = build_call_bridge_window(tmp_path, monkeypatch)
    yield window
    window.stop_call_bridge()
    window.close()


def remove_voice(window, language: str) -> None:
    Path(window.config.tts.voices[language]).unlink()


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


@pytest.mark.parametrize("prepare_fails", [False, True])
def test_a_failed_call_bridge_start_restores_start_from_the_mode_availability(
    window,
    spies,  # noqa: F811
    prepare_fails,
) -> None:
    """WI-05/WI-06 hand-off: a failed Call Bridge start re-runs ``_refresh_availability``."""
    import shutil

    assign(window)
    assert window.start_button.isEnabled()
    spies.release_warm_up.clear()  # hold the Call Bridge start while its models load
    if prepare_fails:
        spies.failing_warm_up_calls = {1}

    click(window.call_bridge_panel.start_button)
    assert not window.start_button.isEnabled()
    # The shared recognition model disappears: the conversation mode is unavailable too.
    shutil.rmtree(window.config.speech_to_text.model_path)
    spies.release_warm_up.set()

    expected = (
        "Models could not be prepared: warm-up 1 failed"
        if prepare_fails
        else "Not available: missing speech recognition German, "
        "speech recognition Mandarin (Simplified)"
    )
    assert wait_until(lambda: bridge_notice(window) == expected)
    assert window.call_bridge_controller is None
    assert not window.start_button.isEnabled()  # not blindly re-enabled
    assert window.pair_combo.isEnabled()


def test_a_call_bridge_setup_error_restores_start_from_the_mode_availability(
    window,
    spies,  # noqa: F811
    monkeypatch,
) -> None:
    """WI-05/WI-06 hand-off: any other setup error also re-runs ``_refresh_availability``."""
    import shutil

    from lianiq.ui.workspaces import call_bridge

    def failing_controller(*args, **kwargs):
        raise RuntimeError("call endpoint stream failed")

    monkeypatch.setattr(call_bridge, "FullDuplexBridgeController", failing_controller)
    assign(window)
    spies.release_warm_up.clear()  # hold the Call Bridge start while its models load

    click(window.call_bridge_panel.start_button)
    # The shared recognition model disappears: the conversation mode is unavailable too.
    shutil.rmtree(window.config.speech_to_text.model_path)
    spies.release_warm_up.set()

    assert wait_until(
        lambda: bridge_notice(window) == "Call Bridge could not start: call endpoint stream failed"
    )
    assert window.call_bridge_controller is None
    assert not window.start_button.isEnabled()  # not blindly re-enabled
    assert window.pair_combo.isEnabled()


def test_selecting_another_pair_rebuilds_call_bridge_labels_and_lanes(
    tmp_path,
    spies,  # noqa: F811
    monkeypatch,
) -> None:
    """WI-05/WI-06 hand-off: the pair selector updates the Call Bridge panel."""
    from lianiq.call_bridge.contracts import CallBridgeLanes
    from lianiq.config import TranslationEdgeConfig
    from lianiq.languages import BUILTIN_LANGUAGES, LanguageRegistry
    from tests.languages.synthetic import QAA, SYNTHETIC_LANGUAGES
    from tests.test_requirement_scoped_loading import model_dir

    def add_german_synthetic_pair(config, root) -> None:
        config.speech_to_text.languages = [DE, ZH, QAA]
        config.translation.edges["de>qaa"] = TranslationEdgeConfig(
            str(model_dir(root, "mt-de-qaa"))
        )
        config.translation.edges["qaa>de"] = TranslationEdgeConfig(
            str(model_dir(root, "mt-qaa-de"))
        )

    registry = LanguageRegistry((*BUILTIN_LANGUAGES, SYNTHETIC_LANGUAGES[0]))
    window = build_call_bridge_window(
        tmp_path, monkeypatch, registry=registry, configure=add_german_synthetic_pair
    )
    try:
        panel = window.call_bridge_panel
        assert panel.outbound_test_button.text() == "Test Mandarin (Simplified) → call mic"
        index = next(
            i
            for i in range(window.pair_combo.count())
            if window.pair_combo.itemText(i) and "Synthetic A" in window.pair_combo.itemText(i)
        )

        window.pair_combo.setCurrentIndex(index)

        assert window.config.languages.pair == [DE, QAA]
        assert panel.role_label_widgets[EndpointRole.CALL_MICROPHONE_RENDER].text() == (
            "Call microphone output · Synthetic A to call"
        )
        assert panel.outbound_test_button.text() == "Test Synthetic A → call mic"
        assert panel.inbound_test_button.text() == "Test German → headphones"
        lanes = CallBridgeLanes.from_session(window.call_bridge_session())
        assert (lanes.outbound.key, lanes.inbound.key) == ("de>qaa", "qaa>de")
    finally:
        window.close()


# AC-18 (pytest-qt UI-nav) and the Call Bridge stop path (CAP-0169 WI-07) ------------------


def test_ac18_call_bridge_and_result_labels_show_registry_names(
    window,
    spies,  # noqa: F811
) -> None:
    from tests.ui.test_main_window_languages import assert_no_language_codes, blocks

    panel = window.call_bridge_panel
    assert {role: label.text() for role, label in panel.role_label_widgets.items()} == {
        EndpointRole.LOCAL_MICROPHONE: "Local microphone · German source",
        EndpointRole.CALL_MICROPHONE_RENDER: "Call microphone output · Mandarin (Simplified) to call",
        EndpointRole.CALL_SPEAKER_CAPTURE: "Call speaker input · Mandarin (Simplified) from call",
        EndpointRole.LOCAL_HEADPHONES: "Local headphones · German playback",
    }
    assert panel.outbound_test_button.text() == "Test Mandarin (Simplified) → call mic"
    assert panel.inbound_test_button.text() == "Test German → headphones"
    assign(window)

    click(panel.start_button)
    assert wait_until(lambda: window.call_bridge_controller is not None)
    controller = window.call_bridge_controller
    outbound_capture, inbound_capture = FakeCaptureStream.instances
    spies.recognizer.results = [
        Transcript("Guten Tag", None, 1.0, 0.1),
        Transcript("你好", None, 1.0, 0.1),
    ]
    outbound_capture.on_utterance(AUDIO)
    assert controller.outbound_lane.wait_until_idle(timeout=2.0)
    inbound_capture.on_utterance(AUDIO)
    assert controller.inbound_lane.wait_until_idle(timeout=2.0)
    assert wait_until(lambda: len(window.history) == 2)

    assert blocks(window.source_text) == ["German: Guten Tag", "Mandarin (Simplified): 你好"]
    assert blocks(window.target_text) == [
        "Mandarin (Simplified): [de>zh-Hans] Guten Tag",
        "German: [zh-Hans>de] 你好",
    ]
    assert_no_language_codes(window)


def test_stopping_the_call_bridge_restores_start_from_the_current_availability(
    window,
    spies,  # noqa: F811
) -> None:
    import shutil

    assign(window)
    click(window.call_bridge_panel.start_button)
    assert wait_until(lambda: window.call_bridge_controller is not None)
    assert not window.start_button.isEnabled()
    # The speech recognition model disappears while the Call Bridge runs.
    shutil.rmtree(window.config.speech_to_text.model_path)

    click(window.call_bridge_panel.stop_button)

    assert window.call_bridge_controller is None
    assert not window.start_button.isEnabled()  # not blindly re-enabled
    assert window.state_label.text() == "Not available"
    assert window.pair_combo.isEnabled()  # the session lock is released
    assert window.call_bridge_panel.start_button.isEnabled()
