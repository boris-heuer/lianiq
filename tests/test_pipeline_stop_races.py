"""Turns and resolutions that race a session stop (W2-F1, W2-F2).

Split from ``test_pipeline.py``; the shared fakes are in ``tests/_pipeline_helpers.py``.
"""

from __future__ import annotations

import threading

import pytest

from lianiq.pipeline import TranslationPipeline
from tests._pipeline_helpers import (
    DE,
    ZH,
    FakeRecognizer,
    FakeTranslator,
    bound,
    claim_and_block_resolution,
)


def test_a_turn_being_resolved_is_claimed_and_leaves_no_trace_of_discard() -> None:
    entered, release = threading.Event(), threading.Event()

    class BlockingTranslator(FakeTranslator):
        def translate(self, text, edge, context=()):
            entered.set()
            assert release.wait(timeout=5.0)
            return super().translate(text, edge, context)

    pipeline = TranslationPipeline(FakeRecognizer(detected="en"), BlockingTranslator(), None, None)
    held = pipeline.process(bound())
    outcome: list[object] = []
    resolving = threading.Thread(target=lambda: outcome.append(pipeline.resolve(held, DE)))
    resolving.start()
    assert entered.wait(timeout=2.0)

    # Neither call waits for the running translation; the claimed turn is no longer held.
    assert pipeline.held_turns() == ()
    assert pipeline.discard(held) is False
    assert pipeline.discard_held() == ()
    release.set()
    resolving.join(timeout=2.0)

    assert [(r.turn_id, r.source_language) for r in outcome] == [(held.turn_id, DE)]
    assert pipeline.held_turns() == ()


@pytest.mark.parametrize("stop_step", ["reset_context", "discard_held", "both"])
def test_w2f1_a_claimed_resolution_waiting_for_the_turn_lock_does_not_survive_stop(
    stop_step,
) -> None:
    recognizer = FakeRecognizer(detected="en")
    translator = FakeTranslator()
    pipeline = TranslationPipeline(recognizer, translator, None, None)
    held = pipeline.process(bound())
    pipeline.context.add(ZH, "旧", "alt")
    outcome: list[object] = []
    resolving = claim_and_block_resolution(pipeline, held, outcome)

    # Session stop (SessionController.stop order: reset the context, then discard held turns).
    if stop_step in ("reset_context", "both"):
        pipeline.reset_context()
    if stop_step in ("discard_held", "both"):
        assert pipeline.discard_held() == ()
    pipeline._turn_lock.release()
    resolving.join(timeout=2.0)

    assert outcome == [None]  # dropped: no result
    assert recognizer.calls == [None]  # no forced re-recognition ran
    assert translator.calls == []
    assert pipeline.held_turns() == ()  # dropped, not held again
    assert pipeline.context.source_context(DE) == ()


def test_w2f1_a_resolution_still_recognising_at_stop_is_dropped_before_translation() -> None:
    entered, release = threading.Event(), threading.Event()

    class BlockingForcedRecognizer(FakeRecognizer):
        def transcribe(self, samples, sample_rate, language=None):
            if language is not None:
                entered.set()
                assert release.wait(timeout=5.0)
            return super().transcribe(samples, sample_rate, language)

    translator = FakeTranslator()
    pipeline = TranslationPipeline(BlockingForcedRecognizer(detected="en"), translator, None, None)
    held = pipeline.process(bound())
    outcome: list[object] = []
    resolving = threading.Thread(target=lambda: outcome.append(pipeline.resolve(held, DE)))
    resolving.start()
    assert entered.wait(timeout=2.0)

    pipeline.reset_context()
    pipeline.discard_held()
    release.set()
    resolving.join(timeout=2.0)

    assert outcome == [None]
    assert translator.calls == []
    assert pipeline.held_turns() == ()


def test_w2f1_a_resolution_without_stop_is_unaffected_by_the_epoch_check() -> None:
    pipeline = TranslationPipeline(FakeRecognizer(detected="en"), FakeTranslator(), None, None)
    held = pipeline.process(bound())
    outcome: list[object] = []
    resolving = claim_and_block_resolution(pipeline, held, outcome)
    pipeline._turn_lock.release()
    resolving.join(timeout=2.0)

    assert [(r.turn_id, r.source_language) for r in outcome] == [(held.turn_id, DE)]


def test_w2f2_a_late_turn_translates_with_an_empty_context_and_never_feeds_the_next() -> None:
    entered, release = threading.Event(), threading.Event()

    class BlockingRecognizer(FakeRecognizer):
        def transcribe(self, samples, sample_rate, language=None):
            entered.set()
            assert release.wait(timeout=5.0)
            return super().transcribe(samples, sample_rate, language)

    translator = FakeTranslator()
    pipeline = TranslationPipeline(BlockingRecognizer(detected="de"), translator, None, None)
    pipeline.context.add(DE, "Vorher", "之前")  # the stopping session's context
    outcome: list[object] = []
    late = threading.Thread(target=lambda: outcome.append(pipeline.process(bound())))
    late.start()
    assert entered.wait(timeout=2.0)

    pipeline.reset_context()  # Stop
    pipeline.context.add(DE, "Neu", "新")  # the next session's context
    release.set()
    late.join(timeout=2.0)

    assert outcome[0].source_language == DE  # the late turn still completes with its pair
    assert translator.calls == [("Guten Tag", "de>zh-Hans", ())]  # empty context, not stale
    assert pipeline.context.source_context(DE) == ("Neu",)  # the next context is untouched


def test_a_late_turn_that_would_be_held_after_stop_is_dropped_with_its_audio() -> None:
    entered, release = threading.Event(), threading.Event()

    class BlockingRecognizer(FakeRecognizer):
        def transcribe(self, samples, sample_rate, language=None):
            entered.set()
            assert release.wait(timeout=5.0)
            return super().transcribe(samples, sample_rate, language)

    translator = FakeTranslator()
    pipeline = TranslationPipeline(BlockingRecognizer(detected="en"), translator, None, None)
    outcome: list[object] = []
    late = threading.Thread(target=lambda: outcome.append(pipeline.process(bound())))
    late.start()
    assert entered.wait(timeout=2.0)

    pipeline.reset_context()  # Stop: the running turn outlives the flush timeout
    assert pipeline.discard_held() == ()
    release.set()
    late.join(timeout=2.0)

    assert outcome == [None]  # never held after the stop, so no bar and no retained audio
    assert pipeline.held_turns() == ()
    assert translator.calls == []


def test_w2f1_a_resolution_that_fails_after_stop_is_not_held_again() -> None:
    entered, release = threading.Event(), threading.Event()

    class FailingForcedRecognizer(FakeRecognizer):
        def transcribe(self, samples, sample_rate, language=None):
            if language is not None:
                entered.set()
                assert release.wait(timeout=5.0)
                raise RuntimeError("model failed")
            return super().transcribe(samples, sample_rate, language)

    pipeline = TranslationPipeline(
        FailingForcedRecognizer(detected="en"), FakeTranslator(), None, None
    )
    held = pipeline.process(bound())
    errors: list[BaseException] = []

    def resolve() -> None:
        try:
            pipeline.resolve(held, DE)
        except RuntimeError as exc:
            errors.append(exc)

    resolving = threading.Thread(target=resolve)
    resolving.start()
    assert entered.wait(timeout=2.0)
    pipeline.reset_context()  # Stop while the resolution runs
    assert pipeline.discard_held() == ()
    release.set()
    resolving.join(timeout=2.0)

    assert [str(error) for error in errors] == ["model failed"]
    assert pipeline.held_turns() == ()  # never back in the held map: audio released
