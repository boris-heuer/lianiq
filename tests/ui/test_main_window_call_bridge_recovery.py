"""MainWindow Call Bridge restore, pair change and stop path (CAP-0169 WI-05/WI-06, WI-07).

Split from ``test_main_window_call_bridge.py``: offscreen clicks over spy adapters,
synthetic endpoints and fake endpoint streams; the shared helpers are in
``_call_bridge_window.py``.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from lianiq.call_bridge.contracts import LaneId
from lianiq.domain import Transcript
from tests._spy_window import spies  # noqa: F401
from tests.call_bridge.support import DE, ZH
from tests.ui._call_bridge_window import (
    AUDIO,
    FakeCaptureStream,
    assign,
    bridge_notice,
    build_call_bridge_window,
    call_bridge_window,  # noqa: F401
    click,
    wait_until,
)


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
    from tests._spy_window import model_dir
    from tests.languages.synthetic import QAA, SYNTHETIC_LANGUAGES

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
        outbound, inbound = panel.paths[LaneId.OUTBOUND], panel.paths[LaneId.INBOUND]
        assert outbound.title() == "You → call · German → Mandarin (Simplified)"
        index = next(
            i
            for i in range(window.pair_combo.count())
            if window.pair_combo.itemText(i) and "Synthetic A" in window.pair_combo.itemText(i)
        )

        window.pair_combo.setCurrentIndex(index)

        assert window.config.languages.pair == [DE, QAA]
        assert outbound.title() == "You → call · German → Synthetic A"
        assert inbound.title() == "Call → you · Synthetic A → German"
        lanes = CallBridgeLanes.from_session(window.call_bridge_session())
        assert (lanes.outbound.key, lanes.inbound.key) == ("de>qaa", "qaa>de")
    finally:
        window.close()


# AC-18 (pytest-qt UI-nav) and the Call Bridge stop path (CAP-0169 WI-07) ------------------


def test_ac18_call_bridge_and_result_labels_show_registry_names(
    window,
    spies,  # noqa: F811
) -> None:
    from tests.ui._language_helpers import assert_no_language_codes, blocks

    panel = window.call_bridge_panel
    assert [box.title() for box in panel.paths.values()] == [
        "You → call · German → Mandarin (Simplified)",
        "Call → you · Mandarin (Simplified) → German",
    ]
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
    view, NL = window.call_bridge_panel.text_view, chr(10)
    assert wait_until(lambda: len(view.turns()) == 2)

    # CAP-0166 AC-13: direction, original and translation in the live call text only.
    assert view.turns() == [
        "You → call" + NL + "Guten Tag" + NL + "[de>zh-Hans] Guten Tag",
        "Call → you" + NL + "你好" + NL + "[zh-Hans>de] 你好",
    ]
    assert blocks(window.source_text) == [] and window.history == []
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
    # CAP-0166 AC-02: the Call Bridge Start follows readiness, which names the lost model.
    reasons = [reason.text for reason in window.call_bridge_panel.reasons]
    assert any("speech recognition" in text for text in reasons)
    assert not window.call_bridge_panel.start_button.isEnabled()
