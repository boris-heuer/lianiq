"""Notices in the shell (CAP-0168 WI-03; spec §2.3.4, §2.2.3, §2.2.5): offscreen UI tests.

AC-24 (UI): each mapped Conversation failure shows exactly one notice in the workspace
banner naming what failed, the mode/language, whether recording/playback continues and its
action. Device loss, export failure and "+N more" are in ``test_shell_notices_devices.py``;
AC-25 (Retry), AC-26 (accessible name, focus) and the banner focus rules are in
``test_shell_notices_focus.py``; the shared helpers are in ``_notice_helpers.py``.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from lianiq.pipeline import PipelineEvent, PipelineEventKind
from tests._spy_window import build_window, spies  # noqa: F401
from tests.ui._language_helpers import start, submit, transcript, wait_until
from tests.ui._notice_helpers import (
    CONVERSATION,
    PAIR_SOURCE,
    SPEAKERS,
    banner,
    notice_window,  # noqa: F401
    shown,
)
from tests.ui.test_main_window_session import click

# AC-24 (UI) -------------------------------------------------------------------------------


def test_no_notice_no_banner(window) -> None:
    assert window.notices.live() == ()
    assert not banner(window).isVisible()


def test_ac24_mode_unavailable_is_one_blocking_notice_with_retry(window) -> None:
    window.devices = [SPEAKERS]  # no microphone enumerated
    window.start_listening()

    title, detail, labels = shown(window)
    assert title == "Action needed: Not available: missing microphone"
    assert detail.startswith(PAIR_SOURCE + ". Recording has not started.")
    assert labels == ["Retry"]
    assert window.notices.count(CONVERSATION) == 1
    assert not window.capture.running


def test_ac24_model_failure_is_one_blocking_notice(window, spies) -> None:  # noqa: F811
    spies.failing_warm_up_calls = {1}
    click(window.start_button)
    assert wait_until(lambda: window.state_label.text() == "Model error")

    title, detail, labels = shown(window)
    assert title == "Action needed: Models could not be prepared: warm-up 1 failed"
    assert "Recording has not started." in detail and labels == ["Retry"]
    assert window.notices.count(CONVERSATION) == 1


def test_ac24_pair_locked_is_an_info_notice_cleared_by_stop(window) -> None:
    start(window)
    window.conversation._selection_changed()  # a selection change reaches the locked gate

    title, detail, labels = shown(window)
    assert title == "Information: Stop the session to change language pair or mode"
    assert "Recording continues." in detail and "Press Stop (F9) first." in detail
    assert labels == []
    window.stop_listening()
    assert window.notices.live() == () and not banner(window).isVisible()


def test_ac24_held_turns_discarded_on_stop_is_a_warning(window, spies) -> None:  # noqa: F811
    start(window)
    submit(window, spies, transcript("It is a test.", "en"))
    assert wait_until(window.held_turn_bar.isVisible)
    assert not banner(window).isVisible()  # the held-turn bar stays primary while running

    click(window.stop_button)

    title, detail, labels = shown(window)
    assert title == "Warning: 1 turn(s) with an unclear language were discarded"
    assert "Recording stopped. Your transcript is kept." in detail
    assert "No action needed" in detail and labels == []
    assert banner(window).dismiss_button.isVisible()
    click(banner(window).dismiss_button)
    assert not banner(window).isVisible() and window.notices.live() == ()


@pytest.mark.parametrize(
    ("event", "expected", "continues"),
    [
        (
            PipelineEvent(PipelineEventKind.QUEUE_OVERFLOW),
            "Warning: The audio queue was full; the oldest pending segment was dropped.",
            "Recording continues.",
        ),
        (
            PipelineEvent(PipelineEventKind.TURNS_DROPPED, count=2),
            (
                "Warning: 2 queued speech segment(s) were not translated before the session "
                "stopped and were dropped."
            ),
            "Recording stopped.",
        ),
    ],
)
def test_ac24_pipeline_overflow_and_dropped_turns_are_notices(window, event, expected, continues):
    start(window)
    window.runner.on_event(event)  # what the pipeline worker reports
    window.runner.on_event(event)  # a repeat updates the one notice

    title, detail, labels = shown(window)
    assert title == f"{expected} (2×)"
    assert continues in detail and "Conversation" in detail and labels == []
    assert window.notices.count(CONVERSATION) == 1


def test_ac24_a_pipeline_event_of_an_older_session_is_dropped(window) -> None:
    start(window)
    old = window.session_owner.generation
    window.stop_listening()
    start(window)
    window.bridge.pipeline_event.emit(PipelineEvent(PipelineEventKind.QUEUE_OVERFLOW), old)
    assert window.notices.live() == ()
    window.bridge.pipeline_event.emit(
        PipelineEvent(PipelineEventKind.QUEUE_OVERFLOW), window.session_owner.generation
    )
    assert window.notices.count(CONVERSATION) == 1


def test_ac24_missing_voice_is_a_warning_with_text_only_output(tmp_path, spies, monkeypatch):  # noqa: F811
    from tests.ui._language_helpers import without_mandarin_voice

    window = build_window(tmp_path, monkeypatch, configure=without_mandarin_voice)
    try:
        title, detail, labels = shown(window)
        assert title == "Warning: Not available: missing voice Mandarin (Simplified)"
        assert "translations appear as text only" in detail and labels == []
        window.mode_combo.setCurrentText("Mandarin (Simplified) → German")  # German voice exists
        assert window.notices.live() == () and not banner(window).isVisible()
    finally:
        window.close()
