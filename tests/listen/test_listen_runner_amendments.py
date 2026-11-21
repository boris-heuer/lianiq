"""CAP-0170 contract §5 and §7: hook, TURN_FAILED, submit_bound, wait_idle (AC-24, AC-29)."""

from __future__ import annotations

import threading

from lianiq.listen.session import listen_session
from lianiq.pipeline import PipelineRunner, TranslationPipeline
from lianiq.pipeline_types import FailureReason, PipelineEventKind, classify_failure
from lianiq.text_translation import jobs
from tests._pipeline_helpers import AUTOMATIC, DE, PAIR, FakeRecognizer, FakeTranslator, bound

LISTEN = listen_session(PAIR, DE)


class FailingPipeline:
    def process(self, item):
        raise FileNotFoundError("secret model path")


def test_failure_reason_moved_and_still_importable_from_jobs() -> None:
    assert jobs.FailureReason is FailureReason
    assert jobs.failure_reason is classify_failure
    assert classify_failure(MemoryError()) is FailureReason.MEMORY


def test_on_recognized_sees_every_segment_and_a_failing_hook_is_ignored() -> None:
    seen = []
    pipeline = TranslationPipeline(FakeRecognizer(text=""), FakeTranslator())
    pipeline.on_recognized = lambda item, transcript: seen.append(transcript.text)
    assert pipeline.process(bound(LISTEN)) is None
    assert seen == [""]
    pipeline.recognizer = FakeRecognizer(text="Hallo")
    pipeline.on_recognized = lambda item, transcript: 1 / 0
    assert pipeline.process(bound(LISTEN)).source_text == "Hallo"


def run_one(runner: PipelineRunner, item) -> None:
    runner.start(item.session)
    runner.submit_bound(item)
    runner.stop(timeout=5.0)


def test_report_turn_failures_emits_turn_failed_instead_of_on_error() -> None:
    events, errors = [], []
    runner = PipelineRunner(
        FailingPipeline(),
        lambda r: None,
        errors.append,
        on_event=events.append,
        report_turn_failures=True,
    )
    item = bound(LISTEN)
    run_one(runner, item)
    assert errors == []
    assert [(e.kind, e.turn_id, e.failure) for e in events] == [
        (PipelineEventKind.TURN_FAILED, item.turn_id, FailureReason.MODEL)
    ]


def test_default_runner_keeps_on_error() -> None:
    events, errors = [], []
    runner = PipelineRunner(
        FailingPipeline(), lambda r: None, errors.append, on_event=events.append
    )
    run_one(runner, bound(LISTEN))
    assert errors == ["secret model path"] and events == []


def test_submit_bound_ignores_another_session_and_overflow_names_the_dropped_turn() -> None:
    release = threading.Event()
    started = threading.Event()

    class Blocking:
        def process(self, item):
            started.set()
            release.wait(5.0)

    events = []
    runner = PipelineRunner(
        Blocking(), lambda r: None, lambda e: None, max_pending=1, on_event=events.append
    )
    runner.start(LISTEN)
    runner.submit_bound(bound(AUTOMATIC))  # other session: ignored
    runner.submit_bound(bound(LISTEN))
    assert started.wait(5.0)
    oldest, newest = bound(LISTEN), bound(LISTEN)
    runner.submit_bound(oldest)
    runner.submit_bound(newest)
    assert [(e.kind, e.turn_id) for e in events] == [
        (PipelineEventKind.QUEUE_OVERFLOW, oldest.turn_id)
    ]
    assert not runner.wait_idle(0.05)
    release.set()
    runner.stop(timeout=5.0)
    assert runner.wait_idle(0.0)
