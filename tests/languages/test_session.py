"""Session lifecycle and transcript export v2 (CAP-0169 AC-14, AC-15; contract.md §3.1.7).

WI-06 adds the AC-13 UI lock cases; this file covers ``SessionController`` itself.
"""

from __future__ import annotations

import dataclasses
import threading
import time
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import numpy as np
import pytest

from lianiq.conversation.routing import HeldTurn
from lianiq.domain import AudioUtterance, Transcript, TranslationResult
from lianiq.languages import (
    BUILTIN_LANGUAGES,
    TRANSCRIPT_V2_HEADER,
    DeviceReadiness,
    InputKind,
    LanguageId,
    LanguageRegistry,
    ModeUnavailableError,
    OutputKind,
    PairLockedError,
    Requirement,
    RequirementKind,
    RoutingKind,
    SessionController,
    SessionPair,
    UsageMode,
    format_transcript_v2,
)
from lianiq.pipeline import PipelineRunner, TranslationPipeline
from tests.languages.synthetic import QAA, QAB, SYNTHETIC_LANGUAGES, provisioned_catalog

DE = LanguageId("de")
ZH = LanguageId("zh-Hans")
REGISTRY = LanguageRegistry(BUILTIN_LANGUAGES + SYNTHETIC_LANGUAGES)
DE_ZH = REGISTRY.pair(DE, ZH)
QAA_QAB = REGISTRY.pair(QAA, QAB)
MICROPHONE_TEXT = UsageMode(InputKind.MICROPHONE, RoutingKind.BIDIRECTIONAL, OutputKind.TEXT)
AUTOMATIC = SessionPair(DE_ZH, MICROPHONE_TEXT)
ALL_EDGES = ("de>zh-Hans", "zh-Hans>de", "qaa>qab", "qab>qaa")
AUDIO = AudioUtterance(np.zeros(1_600, dtype=np.float32), 16_000)


def fixed(source: LanguageId, output: OutputKind = OutputKind.TEXT) -> SessionPair:
    mode = UsageMode(InputKind.MICROPHONE, RoutingKind.FIXED, output)
    return SessionPair(DE_ZH, mode, fixed_source=source)


class ScriptedRecognizer:
    """Returns scripted (language, text) transcripts; the first call can block."""

    def __init__(self, script, gate: threading.Event | None = None) -> None:
        self.script = list(script)
        self.gate = gate
        self.started = threading.Event()
        self.calls: list[str | None] = []

    def transcribe(self, samples, sample_rate, language=None):
        self.calls.append(language)
        self.started.set()
        if self.gate is not None:
            assert self.gate.wait(timeout=5.0)
        detected, text = self.script.pop(0)
        return Transcript(text, LanguageId(detected), 0.99, 0.1, detected)


class TaggingTranslator:
    def __init__(self) -> None:
        self.calls = []

    def translate(self, text, edge, context=()):
        self.calls.append((text, edge.key, tuple(context)))
        return f"[{edge.key}] {text}"


class RecordingCapture:
    def __init__(self, events: list[str], fail: bool = False) -> None:
        self.events = events
        self.fail = fail

    def start(self) -> None:
        self.events.append("capture.start")
        if self.fail:
            raise RuntimeError("no microphone")

    def stop(self) -> None:
        self.events.append("capture.stop")


class Harness:
    def __init__(self, tmp_path, recognizer, *, voices=(), capture_fails=False) -> None:
        self.events: list[str] = []
        self.results: list[TranslationResult] = []
        self.held: list[HeldTurn] = []
        self.errors: list[str] = []
        catalog = provisioned_catalog(
            tmp_path,
            REGISTRY,
            recognition=(DE, ZH, QAA, QAB),
            edges=ALL_EDGES,
            voices=voices,
        )
        self.translator = TaggingTranslator()
        self.pipeline = TranslationPipeline(
            recognizer, self.translator, None, None, registry=REGISTRY, catalog=catalog
        )
        self.runner = PipelineRunner(
            self.pipeline,
            on_result=self.results.append,
            on_error=self.errors.append,
            on_held=self.held.append,
        )
        self.capture = RecordingCapture(self.events, fail=capture_fails)
        self.controller = SessionController(
            self.pipeline,
            self.runner,
            devices=lambda: DeviceReadiness(microphone=True, playback=False),
            capture=self.capture,
        )

    def context_is_empty(self) -> bool:
        return all(self.pipeline.context.source_context(lang) == () for lang in (DE, ZH, QAA))


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


def result(
    captured_at: datetime, source: str = DE, target: str = ZH, text: str = "Guten Tag"
) -> TranslationResult:
    return TranslationResult(
        uuid4(), captured_at, text, f"[{source}>{target}] {text}", source, target, 0.1, 0.2
    )


T0 = datetime(2026, 11, 2, 10, 15, 3, tzinfo=timezone(timedelta(hours=1)))


def test_ac15_translation_result_is_frozen() -> None:
    completed = result(T0)

    for field, value in (("source_language", ZH), ("target_language", DE), ("source_text", "x")):
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(completed, field, value)


def test_export_v2_format_orders_lines_by_capture_time() -> None:
    later = result(T0 + timedelta(seconds=5), ZH, DE, "你好")
    earlier = result(T0)

    text = format_transcript_v2(DE_ZH, [later, earlier])

    assert text.splitlines() == [
        "# lianiq transcript v2",
        "# pair: de zh-Hans",
        "[2026-11-02T10:15:03+01:00] de -> zh-Hans",
        "de: Guten Tag",
        "zh-Hans: [de>zh-Hans] Guten Tag",
        "",
        "[2026-11-02T10:15:08+01:00] zh-Hans -> de",
        "zh-Hans: 你好",
        "de: [zh-Hans>de] 你好",
    ]
    assert text.startswith(TRANSCRIPT_V2_HEADER + "\n")
    assert text.endswith("\n")


def test_ac15_completed_turns_keep_their_languages_after_routing_output_and_pair_change(
    tmp_path,
) -> None:
    recognizer = ScriptedRecognizer(
        [("de", "Guten Tag"), ("zh-Hans", "你好"), ("zh-Hans", "谢谢"), ("qab", "beta")]
    )
    harness = Harness(tmp_path, recognizer, voices=(DE, ZH))
    sessions = [
        AUTOMATIC,  # Automatic de/zh-Hans, text
        fixed(ZH),  # routing change
        fixed(ZH, OutputKind.SPOKEN),  # output change
        SessionPair(QAA_QAB, MICROPHONE_TEXT),  # pair change
    ]
    snapshots = []
    exports = []
    harness.controller.devices = lambda: DeviceReadiness(microphone=True, playback=True)
    for session in sessions:
        harness.controller.start(session)
        harness.runner.submit(AUDIO)
        harness.controller.stop()
        snapshots.append(dataclasses.astuple(harness.results[0]))
        exports.append(format_transcript_v2(DE_ZH, harness.results))

    first = harness.results[0]
    assert [(r.source_language, r.target_language) for r in harness.results] == [
        (DE, ZH),
        (ZH, DE),
        (ZH, DE),
        (QAB, QAA),
    ]
    assert snapshots == [dataclasses.astuple(first)] * len(sessions)
    direction = f"[{first.captured_at.isoformat(timespec='seconds')}] de -> zh-Hans"
    for export in exports:
        lines = export.splitlines()
        assert lines[0] == "# lianiq transcript v2"
        assert lines[2:5] == [direction, "de: Guten Tag", "zh-Hans: [de>zh-Hans] Guten Tag"]
    last = harness.results[-1]
    assert exports[-1].splitlines()[-3:] == [
        f"[{last.captured_at.isoformat(timespec='seconds')}] qab -> qaa",
        "qab: beta",
        "qaa: [qab>qaa] beta",
    ]
