"""PipelineRunner: the bound session, stop flushing, dropped items and background resolution.

Split from ``test_pipeline.py``; the shared fakes are in ``tests/_pipeline_helpers.py``.
"""

from __future__ import annotations

import threading

from lianiq.pipeline import PipelineRunner, TranslationPipeline
from tests._pipeline_helpers import (
    AUTOMATIC,
    DE,
    ZH_TO_DE,
    FakeRecognizer,
    FakeTranslator,
    RecordingPipeline,
    bound,
    gated_queue_class,
    utterance,
)


def test_runner_binds_the_started_session_to_each_submitted_item() -> None:
    pipeline = RecordingPipeline()
    runner = PipelineRunner(pipeline, on_result=lambda _r: None, on_error=lambda _m: None)
    runner.start(ZH_TO_DE)
    runner.submit(utterance())

    assert runner.stop() == 0
    assert [item.session for item in pipeline.items] == [ZH_TO_DE]
    assert runner.session is None
    runner.submit(utterance())  # a stopped runner accepts nothing
    assert len(pipeline.items) == 1


def test_runner_waits_for_active_processing_during_stop() -> None:
    release = threading.Event()
    pipeline = RecordingPipeline(release)
    runner = PipelineRunner(pipeline, on_result=lambda _r: None, on_error=lambda _m: None)
    runner.start(AUTOMATIC)
    runner.submit(utterance())
    assert pipeline.started.wait(timeout=1.0)
    threading.Timer(0.05, release.set).start()

    assert runner.stop(timeout=1.0) == 0

    assert runner._thread is None


def test_runner_stop_finishes_queued_items_with_their_bound_pair() -> None:
    release = threading.Event()
    pipeline = RecordingPipeline(release)
    runner = PipelineRunner(pipeline, on_result=lambda _r: None, on_error=lambda _m: None)
    runner.start(AUTOMATIC)
    runner.submit(utterance())
    assert pipeline.started.wait(timeout=1.0)
    runner.submit(utterance())
    runner.submit(utterance())  # two queued behind the active one
    threading.Timer(0.05, release.set).start()

    assert runner.stop(timeout=5.0) == 0
    assert len(pipeline.items) == 3
    assert {item.session for item in pipeline.items} == {AUTOMATIC}


def test_runner_reports_queued_items_it_could_not_finish_as_dropped() -> None:
    release = threading.Event()
    pipeline = RecordingPipeline(release)
    errors: list[str] = []
    runner = PipelineRunner(pipeline, on_result=lambda _r: None, on_error=errors.append)
    runner.start(AUTOMATIC)
    runner.submit(utterance())
    assert pipeline.started.wait(timeout=1.0)
    runner.submit(utterance())
    runner.submit(utterance())

    assert runner.stop(timeout=0.2) == 2

    message = (
        "2 queued speech segment(s) were not translated before the session stopped and were "
        "dropped."
    )
    assert errors == [message]
    release.set()
    runner._thread.join(timeout=2.0)
    assert len(pipeline.items) == 1


def test_runner_reports_held_turns_and_resolves_them_in_the_background() -> None:
    pipeline = TranslationPipeline(FakeRecognizer(detected="en"), FakeTranslator(), None, None)
    results, held, errors = [], [], []
    runner = PipelineRunner(
        pipeline, on_result=results.append, on_error=errors.append, on_held=held.append
    )
    runner.start(AUTOMATIC)
    runner.submit(utterance())
    runner._queue.join()

    assert len(held) == 1 and results == []
    runner.resolve(held[0], DE).join(timeout=2.0)

    assert runner.stop() == 0
    assert errors == []
    assert [(r.turn_id, r.source_language) for r in results] == [(held[0].turn_id, DE)]


def test_runner_resolve_reports_completion_even_when_the_resolution_is_dropped() -> None:
    pipeline = TranslationPipeline(FakeRecognizer(detected="en"), FakeTranslator(), None, None)
    held = pipeline.process(bound())
    results, errors, done = [], [], threading.Event()
    runner = PipelineRunner(pipeline, on_result=results.append, on_error=errors.append)
    pipeline.discard(held)

    runner.resolve(held, DE, on_done=done.set).join(timeout=2.0)

    assert done.is_set()
    assert results == []
    assert errors == ["The held turn is no longer pending"]


def test_w2f2_an_item_taken_while_stop_aborts_is_either_started_or_counted_dropped(
    monkeypatch,
) -> None:
    """The abort under ``_take_lock``: no taken item is lost outside ``StopReport.dropped``."""
    import lianiq.pipeline as pipeline_module

    taken, release = threading.Event(), threading.Event()
    monkeypatch.setattr(pipeline_module.queue, "Queue", gated_queue_class(taken, release))
    pipeline = RecordingPipeline()
    errors: list[str] = []
    runner = PipelineRunner(pipeline, on_result=lambda _r: None, on_error=errors.append)
    runner.start(AUTOMATIC)
    runner.submit(utterance())
    assert taken.wait(timeout=2.0)  # the worker holds the item, not yet started
    runner.submit(utterance())  # one more waits in the queue

    outcome: list[int] = []
    stopping = threading.Thread(target=lambda: outcome.append(runner.stop(timeout=0.1)))
    stopping.start()
    threading.Event().wait(0.3)  # stop's join timed out; it now aborts under the take lock
    release.set()
    stopping.join(timeout=2.0)
    if runner._thread is not None:
        runner._thread.join(timeout=2.0)

    dropped = outcome[0]
    # Every submitted item is either processed or counted as dropped exactly once.
    assert len(pipeline.items) + dropped == 2
    assert len(pipeline.items) >= 1  # the taken item was started, never silently dropped
    reported = sum(int(message.split()[0]) for message in errors if "dropped" in message)
    assert reported == dropped
