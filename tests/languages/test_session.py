"""Session lifecycle and transcript export v2 (CAP-0169 AC-14, AC-15; contract.md §3.1.7).

WI-06 adds the AC-13 UI lock cases; this file covers ``SessionController`` itself. The
harness is in ``_session_harness.py``; the AC-15 export and AC-13 lock tests are in
``test_session_export.py``.
"""

from __future__ import annotations

import threading
import time

import pytest

from lianiq.languages import (
    ModeUnavailableError,
    OutputKind,
    PairLockedError,
    Requirement,
    RequirementKind,
    SessionPair,
)
from tests.languages._session_harness import (
    AUDIO,
    AUTOMATIC,
    DE,
    MICROPHONE_TEXT,
    QAA_QAB,
    ZH,
    Harness,
    ScriptedRecognizer,
    fixed,
)


def test_start_refuses_a_session_with_unmet_requirements(tmp_path) -> None:
    harness = Harness(tmp_path, ScriptedRecognizer([]))  # no voice, no playback

    with pytest.raises(ModeUnavailableError) as error:
        harness.controller.start(fixed(DE, OutputKind.SPOKEN))

    assert error.value.missing == (
        Requirement(RequirementKind.VOICE, ZH),
        Requirement(RequirementKind.PLAYBACK),
    )
    assert not harness.controller.running
    assert harness.events == []  # capture never started
    assert harness.runner.session is None


def test_a_running_session_is_locked(tmp_path) -> None:
    harness = Harness(tmp_path, ScriptedRecognizer([]))
    harness.controller.start(AUTOMATIC)

    with pytest.raises(PairLockedError, match="Stop the session"):
        harness.controller.change(fixed(DE))
    with pytest.raises(PairLockedError):
        harness.controller.start(fixed(DE))

    assert harness.controller.session == AUTOMATIC
    harness.controller.stop()
    assert harness.controller.change(fixed(DE)).available
    assert harness.controller.session == fixed(DE)


def test_stop_order_capture_first_then_flush_reset_and_discard(tmp_path) -> None:
    recognizer = ScriptedRecognizer([("en", "Hello"), ("de", "Hallo")])
    harness = Harness(tmp_path, recognizer)
    harness.controller.start(AUTOMATIC)
    harness.runner.submit(AUDIO)
    harness.runner._queue.join()
    harness.runner.submit(AUDIO)
    record_stop_steps(harness)

    report = harness.controller.stop()

    assert harness.events == [
        "capture.start",
        "capture.stop",
        "runner.stop",
        "reset_context",
        "discard_held",
    ]
    assert report.dropped == 0
    assert report.discarded == tuple(harness.held)  # the unresolved "en" turn
    assert [r.source_language for r in harness.results] == [DE]  # flushed, not dropped
    assert harness.pipeline.held_turns() == ()
    assert harness.context_is_empty()
    assert not harness.controller.running


def record_stop_steps(harness: Harness) -> None:
    for owner, name in (
        (harness.runner, "stop"),
        (harness.pipeline, "reset_context"),
        (harness.pipeline, "discard_held"),
    ):
        original = getattr(owner, name)
        label = "runner.stop" if owner is harness.runner else name

        def recorded(*args, _original=original, _label=label, **kwargs):
            harness.events.append(_label)
            return _original(*args, **kwargs)

        setattr(owner, name, recorded)


def test_stop_still_resets_discards_and_unlocks_when_capture_stop_fails(tmp_path) -> None:
    harness = Harness(tmp_path, ScriptedRecognizer([("en", "Hello")]))
    harness.controller.start(AUTOMATIC)
    harness.runner.submit(AUDIO)
    harness.runner._queue.join()
    harness.pipeline.context.add(DE, "Guten Tag", "你好")

    def failing_stop() -> None:
        raise RuntimeError("device vanished")

    harness.capture.stop = failing_stop

    with pytest.raises(RuntimeError, match="device vanished"):
        harness.controller.stop()

    assert not harness.controller.running
    assert harness.runner._thread is None  # the worker was still stopped
    assert harness.pipeline.held_turns() == ()
    assert harness.context_is_empty()


def test_stop_is_bounded_and_a_late_turn_never_feeds_the_next_context(tmp_path) -> None:
    gate = threading.Event()
    recognizer = ScriptedRecognizer([("de", "Guten Tag"), ("de", "Tschüss")], gate)
    harness = Harness(tmp_path, recognizer)
    harness.controller.flush_timeout = 0.2
    harness.controller.start(AUTOMATIC)
    harness.runner.submit(AUDIO)
    assert recognizer.started.wait(timeout=2.0)
    harness.runner.submit(AUDIO)

    started = time.monotonic()
    report = harness.controller.stop()
    elapsed = time.monotonic() - started

    assert elapsed < 1.0  # the running turn does not hold up stop
    assert report.dropped == 1
    message = (
        "1 queued speech segment(s) were not translated before the session stopped and "
        "were dropped."
    )
    assert harness.errors == [message]
    gate.set()
    harness.runner._thread.join(timeout=2.0)
    # The turn that was running completes with its pair, but its context is not kept.
    assert [(r.source_language, r.source_text) for r in harness.results] == [(DE, "Guten Tag")]
    assert harness.context_is_empty()


def test_a_failed_capture_start_leaves_nothing_running(tmp_path) -> None:
    harness = Harness(tmp_path, ScriptedRecognizer([]), capture_fails=True)

    with pytest.raises(RuntimeError, match="no microphone"):
        harness.controller.start(AUTOMATIC)

    assert not harness.controller.running
    assert harness.runner.session is None
    assert harness.runner._thread is None


def test_ac14_queued_turns_keep_their_pair_through_stop_and_pair_change(tmp_path) -> None:
    gate = threading.Event()
    recognizer = ScriptedRecognizer([("de", "Guten Tag"), ("zh-Hans", "你好")], gate)
    harness = Harness(tmp_path, recognizer)
    harness.controller.start(AUTOMATIC)
    harness.runner.submit(AUDIO)
    assert recognizer.started.wait(timeout=2.0)
    harness.runner.submit(AUDIO)  # both utterances are queued under de/zh-Hans
    threading.Timer(0.1, gate.set).start()

    report = harness.controller.stop()
    synthetic = SessionPair(QAA_QAB, MICROPHONE_TEXT)
    availability = harness.controller.change(synthetic)

    assert report.dropped == 0 and harness.errors == []
    assert [(r.source_language, r.target_language) for r in harness.results] == [
        (DE, ZH),
        (ZH, DE),
    ]
    assert [call[1] for call in harness.translator.calls] == ["de>zh-Hans", "zh-Hans>de"]
    assert availability.available
    assert harness.controller.session == synthetic
    assert harness.context_is_empty()


def test_context_resets_when_the_pair_or_mode_changes(tmp_path) -> None:
    harness = Harness(tmp_path, ScriptedRecognizer([]))
    harness.pipeline.context.add(DE, "Guten Tag", "你好")
    harness.controller.change(fixed(DE))
    assert harness.context_is_empty()

    harness.pipeline.context.add(DE, "Guten Tag", "你好")
    harness.controller.change(fixed(DE))  # the same session keeps its context
    assert harness.pipeline.context.source_context(DE) == ("Guten Tag",)
