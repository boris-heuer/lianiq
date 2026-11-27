"""MainWindow Call Bridge setup page (CAP-0166 WI-02): page, readiness and route tests.

AC-01, AC-02 (UI), AC-04, AC-05, AC-06 (UI) and AC-20, clicked offscreen over spy adapters,
synthetic endpoints and fake endpoint streams; no audio device or model is used.
"""

from __future__ import annotations

import os
import threading

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from lianiq.call_bridge.contracts import EndpointRole, LaneId
from lianiq.call_bridge.route_tests import RouteTestState
from lianiq.ui.shell.session_owner import SessionState
from tests._spy_window import spies  # noqa: F401
from tests.call_bridge.support import ZH, mapping
from tests.ui._call_bridge_window import (
    FakeCaptureStream,
    FakePlaybackStream,
    assign,
    bridge_stopped,
    build_call_bridge_window,
    call_bridge_window,  # noqa: F401
    click,
    wait_until,
)

OUT, IN = LaneId.OUTBOUND, LaneId.INBOUND


class HeldPlayback:
    """``play_route_test`` that records the endpoint and plays only when released."""

    def __init__(self, error: Exception | None = None) -> None:
        self.release, self.endpoints, self.error = threading.Event(), [], error

    def __call__(self, endpoint, _path) -> None:
        self.endpoints.append(endpoint.endpoint_id)
        assert self.release.wait(5.0)
        if self.error is not None:
            raise self.error


def row(window, path):
    return window.call_bridge_panel.paths[path]


def unchanged_session(window) -> bool:
    """A route test never starts a session, a controller or a lane status."""
    statuses = {box.status_label.text() for box in window.call_bridge_panel.paths.values()}
    return (
        window.call_bridge_controller is None
        and window.session_owner.state is SessionState.IDLE
        and statuses == {"Stopped"}
        and FakeCaptureStream.instances == []
    )


def test_ac01_opening_call_bridge_opens_no_stream_and_shows_the_note(window) -> None:
    from PySide6.QtWidgets import QCheckBox

    from lianiq.ui.shell.workspaces import WorkspaceId

    click(window.navigation.buttons[WorkspaceId.CALL_BRIDGE])
    panel = window.call_bridge_panel

    page = window.workspace_pages[WorkspaceId.CALL_BRIDGE]
    assert page.findChildren(QCheckBox) == []
    assert panel.experimental_label.isVisible() and panel.checklist_link.isVisible()
    assert FakeCaptureStream.instances == [] and FakePlaybackStream.played == []
    assert not panel.start_button.isEnabled()  # nothing selected yet: readiness names it


def test_ac04_ac05_a_route_test_plays_one_path_and_asks_before_a_result(
    window,
    spies,  # noqa: F811
) -> None:
    held = HeldPlayback()
    window.call_bridge.play_route_test = held
    assign(window)
    outbound = row(window, OUT)

    click(outbound.test_button)

    assert outbound.test_status.text() == "Playing test…"
    assert not outbound.cancel_button.isHidden() and outbound.test_button.isHidden()
    assert unchanged_session(window)
    held.release.set()
    assert wait_until(lambda: outbound.test_status.text() == "Did your partner hear it?")
    assert not outbound.yes_button.isHidden() and not outbound.no_button.isHidden()
    assert held.endpoints == ["id-call_microphone_render"]  # only that path's playback
    assert spies.synthesizer.calls == [("通话麦克风测试。", ZH)]
    click(outbound.yes_button)
    assert outbound.test_status.text() == "Test passed"
    assert outbound.test_status.accessibleName() == "Route test: Test passed"

    click(outbound.test_button)
    assert wait_until(lambda: not outbound.no_button.isHidden())
    click(outbound.no_button)
    assert outbound.test_status.text() == "Test failed — check the call app's microphone setting"
    assert unchanged_session(window)
    assert row(window, IN).test_status.text() == "Not tested"


def test_ac05_cancel_and_a_play_error_end_the_test_without_touching_the_session(
    window,
    spies,  # noqa: F811
) -> None:
    held = HeldPlayback(RuntimeError("endpoint busy"))
    window.call_bridge.play_route_test = held
    assign(window)
    inbound = row(window, IN)

    click(inbound.test_button)
    click(inbound.cancel_button)
    assert inbound.test_status.text() == "Test cancelled"
    held.release.set()  # the late result of the cancelled test is ignored
    assert not wait_until(lambda: inbound.test_status.text() != "Test cancelled", 300)
    assert held.endpoints == ["id-local_headphones"]

    click(inbound.test_button)
    assert wait_until(lambda: inbound.test_status.text() == "Test could not play: endpoint busy")
    assert unchanged_session(window)


def test_ac06_a_device_or_language_change_resets_only_the_affected_path(window) -> None:
    window.call_bridge.play_route_test = lambda endpoint, path: None
    assign(window)
    book = window.call_bridge.route_tests
    for path in (OUT, IN):
        click(row(window, path).test_button)
        assert wait_until(lambda path=path: not row(window, path).yes_button.isHidden())
        click(row(window, path).yes_button)
    assert {book.state(OUT), book.state(IN)} == {RouteTestState.PASSED}

    combo = window.call_bridge_panel.endpoint_combos[EndpointRole.LOCAL_HEADPHONES]
    combo.setCurrentIndex(0)  # a device of Call → you changes

    assert row(window, IN).test_status.text() == "Not tested"
    assert row(window, OUT).test_status.text() == "Test passed"

    window.config.call_bridge.local_language = ZH
    window.call_bridge.update_languages()
    assert row(window, OUT).test_status.text() == "Not tested"


def test_ac02_tests_and_start_are_disabled_while_sessions_run(window) -> None:
    from tests.ui.test_shell_strip import CONVERSATION_BUSY

    panel = window.call_bridge_panel
    assign(window)
    click(window.start_button)  # the conversation holds the session
    assert wait_until(lambda: window.capture.running)

    assert not panel.start_button.isEnabled()
    assert panel.start_button.toolTip() == CONVERSATION_BUSY
    assert [label.accessibleName() for label in panel.readiness_labels] == [CONVERSATION_BUSY]
    window.stop_listening()
    assert panel.start_button.isEnabled() and panel.readiness_list.isHidden()

    click(panel.start_button)
    assert wait_until(lambda: window.call_bridge_controller is not None)
    for path in (OUT, IN):
        assert not row(window, path).test_button.isEnabled()
        assert row(window, path).test_button.toolTip() == "Stop the call bridge to test a path"
    window.stop_call_bridge()
    assert bridge_stopped(window)
    assert row(window, OUT).test_button.isEnabled()


def test_ac20_a_language_without_a_phrase_disables_only_its_test(
    tmp_path,
    spies,  # noqa: F811
    monkeypatch,
) -> None:
    from lianiq.languages import BUILTIN_LANGUAGES, LanguageRegistry
    from tests.languages.synthetic import QAA, SYNTHETIC_LANGUAGES

    registry = LanguageRegistry((*BUILTIN_LANGUAGES, SYNTHETIC_LANGUAGES[0]))
    window = build_call_bridge_window(tmp_path, monkeypatch, registry=registry)
    try:
        window.config.languages.pair = ["de", QAA]
        window.call_bridge.update_languages()
        assign(window)
        outbound, inbound = row(window, OUT), row(window, IN)  # remote Synthetic A, local German
        assert not outbound.test_button.isEnabled()
        assert outbound.test_hint.text() == "No test phrase for Synthetic A"
        assert outbound.test_button.toolTip() == "No test phrase for Synthetic A"
        assert inbound.test_button.isEnabled() and inbound.test_hint.isHidden()
        reasons = [reason.text for reason in window.call_bridge_panel.reasons]
        assert not any("test phrase" in text for text in reasons)  # readiness is unaffected
    finally:
        window.close()


@pytest.mark.parametrize("role", [EndpointRole.LOCAL_MICROPHONE, EndpointRole.CALL_SPEAKER_CAPTURE])
def test_ac15_a_clipping_capture_shows_too_loud_on_its_path(window, role) -> None:
    assign(window)
    click(window.call_bridge_panel.start_button)
    assert wait_until(lambda: window.call_bridge_controller is not None)
    capture = next(c for c in FakeCaptureStream.instances if c.endpoint == mapping()[role])

    capture.on_clip()  # from the capture worker thread in the app

    box = next(b for b in window.call_bridge_panel.paths.values() if b.capture_role is role)
    assert wait_until(lambda: box.level_caption.text().startswith("Too loud (clipping) — lower "))
