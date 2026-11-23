"""CAP-0170 WI-04: overload, stop, navigation, session rules and failures on the Listen page."""
# ruff: noqa: F811 - ``spies`` is the imported fixture

from __future__ import annotations

import threading

import pytest

pytest.importorskip("PySide6")

from lianiq.listen.lifecycle import ListenPhase
from lianiq.listen.transcript import SegmentState
from lianiq.pipeline_types import FailureReason
from lianiq.ui import strings
from lianiq.ui.shell.session_owner import SessionState
from lianiq.ui.shell.workspaces import WorkspaceId
from tests._spy_window import spies  # noqa: F401 - the fixture
from tests.ui._language_packs_helpers import wait_until
from tests.ui._listen_helpers import listen_window, phase_is, speak, start, states

LISTEN = WorkspaceId.LISTEN


@pytest.fixture
def window(tmp_path, monkeypatch, spies):
    window = listen_window(tmp_path, monkeypatch)
    yield window
    window.listen.shutdown()
    window.close()


def gate(spies) -> threading.Event:
    """Hold every translation until the returned event is set."""
    release, translate = threading.Event(), spies.translator.translate

    def gated(text, edge, context=()):
        assert release.wait(5.0)
        return translate(text, edge, context)

    spies.translator.translate = gated
    return release


def keys(window, workspace=LISTEN) -> list[str]:
    return [notice.key for notice in window.notices.live(workspace)]


def test_ac09_overload_skips_the_oldest_waiting_row_and_notices_once(window, spies) -> None:
    start(window)
    release = gate(spies)
    speak(window, spies, *["Hallo."] * 5)  # one in inference, three queued, one more
    assert wait_until(lambda: SegmentState.SKIPPED in states(window))
    assert keys(window).count("listen.overload") == 1
    release.set()
    assert wait_until(lambda: states(window).count(SegmentState.DONE) == 4)
    assert states(window)[1] is SegmentState.SKIPPED
    assert strings.LISTEN_SKIPPED in window.listen.model.index(1).data()


def test_ac10_stop_shows_stopping_at_once_and_finishes_the_queue(window, spies) -> None:
    start(window)
    release = gate(spies)
    speak(window, spies, "Eins.", "Zwei.")
    window.stop_active_session()  # F9
    assert window.listen.controller.phase is ListenPhase.STOPPING
    assert window.listen.state_label.text() == strings.LISTEN_STATE_STOPPING
    assert not window.listen_captures[0].running
    release.set()
    assert phase_is(window, ListenPhase.IDLE)
    assert states(window) == [SegmentState.DONE, SegmentState.DONE]
    assert window.session_owner.state is SessionState.IDLE


def test_ac12_listening_continues_across_navigation_and_f9_stops_it(window, spies) -> None:
    start(window)
    window.show_workspace(WorkspaceId.SETTINGS)
    assert window.session_strip.stop_button.isVisible()
    speak(window, spies, "Hallo.")
    assert wait_until(lambda: states(window) == [SegmentState.DONE])
    window.stop_active_session()
    assert phase_is(window, ListenPhase.IDLE)
    window.show_workspace(LISTEN)
    assert states(window) == [SegmentState.DONE]


def test_ac13_starts_are_refused_both_ways(window, spies) -> None:
    start(window)
    window.conversation.start_listening()
    busy = window.notices.top(WorkspaceId.CONVERSATION)
    assert busy.title == "Stop the Listen & translate session first"
    assert not window.capture.running
    window.stop_active_session()
    assert phase_is(window, ListenPhase.IDLE)
    window.conversation.start_listening()
    assert window.session_owner.active is WorkspaceId.CONVERSATION
    window.listen.start()
    assert window.notices.top(LISTEN).title == "Stop the Conversation session first"
    assert len(window.listen_captures) == 1
    window.stop_active_session()


def test_ac17_failed_segments_show_their_reason_and_listening_continues(window, spies) -> None:
    start(window)
    transcribe, translate = spies.recognizer.transcribe, spies.translator.translate
    calls = {"recognize": 0, "translate": 0}

    def recognize(samples, rate, language=None):
        calls["recognize"] += 1
        if calls["recognize"] == 1:
            raise RuntimeError("secret detail")
        return transcribe(samples, rate, language)

    def failing_translate(text, edge, context=()):
        calls["translate"] += 1
        if calls["translate"] == 1:
            raise MemoryError
        return translate(text, edge, context)

    spies.recognizer.transcribe, spies.translator.translate = recognize, failing_translate
    window.listen_captures[0].speak()  # segment 1: recognition fails
    speak(window, spies, "Zwei.", "Drei.")
    done = [SegmentState.FAILED, SegmentState.FAILED, SegmentState.DONE]
    assert wait_until(lambda: states(window) == done)
    rows = window.listen.controller.transcript.rows
    assert [row.reason for row in rows[:2]] == [FailureReason.OTHER, FailureReason.MEMORY]
    assert strings.LISTEN_REASON_MEMORY in window.listen.model.index(1).data()
    failed = [n for n in window.notices.live(LISTEN) if n.key == "listen.failed"]
    assert len(failed) == 1
    assert "secret" not in failed[0].title and "Zwei" not in failed[0].title


def test_ac18_a_model_load_failure_shows_model_error_and_opens_nothing(window, spies) -> None:
    spies.failing_warm_up_calls.add(1)
    window.start_listening()
    assert wait_until(lambda: "listen-and-translate.model-failed" in keys(window))
    assert window.listen.state_label.text() == strings.LISTEN_STATE_MODEL_ERROR
    assert window.session_owner.state is SessionState.IDLE
    assert window.listen_captures == []


def test_the_listen_pipeline_follows_a_readiness_refresh(window) -> None:
    replacement = object()
    window.pipeline.catalog = replacement
    assert window.listen.pipeline.catalog is replacement
