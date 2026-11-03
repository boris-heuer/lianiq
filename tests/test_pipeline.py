from __future__ import annotations

import dataclasses
import threading

import numpy as np
import pytest

from lianiq.conversation.routing import HeldTurn
from lianiq.domain import AudioUtterance, Transcript
from lianiq.languages import (
    BUILTIN_REGISTRY,
    InputKind,
    LanguageId,
    OutputKind,
    RoutingKind,
    SessionPair,
    UnsupportedModeError,
    UsageMode,
)
from lianiq.pipeline import BoundUtterance, PipelineRunner, TranslationPipeline, bind_utterance

DE = LanguageId("de")
ZH = LanguageId("zh-Hans")
PAIR = BUILTIN_REGISTRY.pair(DE, ZH)
AUTOMATIC = SessionPair(
    PAIR, UsageMode(InputKind.MICROPHONE, RoutingKind.BIDIRECTIONAL, OutputKind.TEXT)
)
ZH_TO_DE = SessionPair(
    PAIR, UsageMode(InputKind.MICROPHONE, RoutingKind.FIXED, OutputKind.TEXT), fixed_source=ZH
)


class FakeRecognizer:
    def __init__(
        self, detected: str | None = "de", text: str = "Guten Tag", code="", probability=0.99
    ) -> None:
        self.detected = None if detected is None else LanguageId(detected)
        self.text = text
        self.code = code
        self.probability = probability
        self.calls: list[str | None] = []

    @property
    def received_language(self):
        return self.calls[-1]

    def transcribe(self, samples, sample_rate, language=None):
        self.calls.append(language)
        detected = language or self.detected
        return Transcript(
            self.text, detected, self.probability, len(samples) / sample_rate, self.code
        )


class FakeTranslator:
    def __init__(self) -> None:
        self.calls = []

    def translate(self, text, edge, context=()):
        self.calls.append((text, edge.key, context))
        return "您好" if edge.target == "zh-Hans" else "Guten Tag"


def utterance() -> AudioUtterance:
    return AudioUtterance(np.zeros(16_000, dtype=np.float32), 16_000)


def bound(session: SessionPair = AUTOMATIC) -> BoundUtterance:
    return bind_utterance(utterance(), session)


def test_auto_mode_uses_detected_direction() -> None:
    recognizer = FakeRecognizer()
    translator = FakeTranslator()
    pipeline = TranslationPipeline(recognizer, translator, None, None)
    item = bound()

    result = pipeline.process(item)

    assert result is not None and not isinstance(result, HeldTurn)
    assert (result.source_language, result.target_language) == (DE, ZH)
    assert (result.turn_id, result.captured_at) == (item.turn_id, item.captured_at)
    assert recognizer.received_language is None
    assert translator.calls == [("Guten Tag", "de>zh-Hans", ())]


def test_manual_mode_forces_whisper_language() -> None:
    recognizer = FakeRecognizer(detected="de", text="你好")
    translator = FakeTranslator()
    pipeline = TranslationPipeline(recognizer, translator, None, None)

    result = pipeline.process(bound(ZH_TO_DE))

    assert recognizer.received_language == "zh-Hans"
    assert result.target_language == DE
    assert translator.calls[0][1] == "zh-Hans>de"


@pytest.mark.parametrize(
    ("detected", "code", "probability", "reason"),
    [
        ("en", "en", 0.99, "out_of_pair"),
        (None, "ja", 0.99, "unregistered"),
        ("de", "de", 0.69, "low_confidence"),
    ],
)
def test_auto_mode_holds_an_unclear_turn_without_translating(
    detected, code, probability, reason
) -> None:
    translator = FakeTranslator()
    pipeline = TranslationPipeline(
        FakeRecognizer(detected=detected, text="您好", code=code, probability=probability),
        translator,
        None,
        None,
    )
    item = bound()

    held = pipeline.process(item)

    assert isinstance(held, HeldTurn)
    assert (held.turn_id, held.captured_at, held.reason) == (
        item.turn_id,
        item.captured_at,
        reason,
    )
    assert held.transcript.engine_language_code == code
    assert translator.calls == []
    assert pipeline.held_turns() == (held,)


def test_resolve_re_recognises_with_the_chosen_source_and_keeps_the_turn_identity() -> None:
    recognizer = FakeRecognizer(detected="en", text="Guten Tag", code="en")
    translator = FakeTranslator()
    pipeline = TranslationPipeline(recognizer, translator, None, None)
    held = pipeline.process(bound())

    result = pipeline.resolve(held, DE)

    assert recognizer.calls == [None, "de"]  # forced re-recognition, no second detection
    assert (result.source_language, result.target_language) == (DE, ZH)
    assert (result.turn_id, result.captured_at) == (held.turn_id, held.captured_at)
    assert translator.calls == [("Guten Tag", "de>zh-Hans", ())]
    assert pipeline.held_turns() == ()  # audio released
    with pytest.raises(LookupError):
        pipeline.resolve(held, DE)


def test_resolve_rejects_a_language_outside_the_bound_pair() -> None:
    pipeline = TranslationPipeline(FakeRecognizer(detected="en"), FakeTranslator(), None, None)
    held = pipeline.process(bound())

    with pytest.raises(UnsupportedModeError):
        pipeline.resolve(held, LanguageId("en"))

    assert pipeline.held_turns() == (held,)


def test_a_failed_resolution_keeps_the_turn_held() -> None:
    class FailingTranslator(FakeTranslator):
        def translate(self, text, edge, context=()):
            raise RuntimeError("model failed")

    pipeline = TranslationPipeline(FakeRecognizer(detected="en"), FailingTranslator(), None, None)
    held = pipeline.process(bound())

    with pytest.raises(RuntimeError, match="model failed"):
        pipeline.resolve(held, DE)

    assert pipeline.held_turns() == (held,)


def test_discard_releases_a_held_turn_and_produces_nothing() -> None:
    translator = FakeTranslator()
    pipeline = TranslationPipeline(FakeRecognizer(detected="en"), translator, None, None)
    first = pipeline.process(bound())
    second = pipeline.process(bound())

    assert pipeline.discard(first) is True
    assert pipeline.discard(first) is False
    assert pipeline.held_turns() == (second,)
    assert pipeline.discard_held() == (second,)
    assert pipeline.held_turns() == ()
    assert translator.calls == []


def test_held_turns_do_not_block_later_turns() -> None:
    class Scripted:
        def __init__(self) -> None:
            self.detections = iter([("en", "Hello"), ("de", "Hallo"), ("zh-Hans", "你好")])

        def transcribe(self, samples, sample_rate, language=None):
            detected, text = next(self.detections)
            return Transcript(text, LanguageId(detected), 0.99, 1.0, detected)

    pipeline = TranslationPipeline(Scripted(), FakeTranslator(), None, None)

    outcomes = [pipeline.process(bound()) for _ in range(3)]

    assert isinstance(outcomes[0], HeldTurn)
    assert [(o.source_language, o.target_language) for o in outcomes[1:]] == [(DE, ZH), (ZH, DE)]


def test_empty_transcript_is_ignored() -> None:
    pipeline = TranslationPipeline(FakeRecognizer(text="  "), FakeTranslator(), None, None)
    assert pipeline.process(bound()) is None


def test_translation_result_is_frozen() -> None:
    result = TranslationPipeline(FakeRecognizer(), FakeTranslator(), None, None).process(bound())

    with pytest.raises(dataclasses.FrozenInstanceError):
        result.source_language = ZH  # type: ignore[misc]


class RecordingPipeline:
    def __init__(self, release: threading.Event | None = None) -> None:
        self.release = release
        self.started = threading.Event()
        self.items: list[BoundUtterance] = []

    def process(self, item):
        self.items.append(item)
        self.started.set()
        if self.release is not None:
            assert self.release.wait(timeout=5.0)


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


def claim_and_block_resolution(pipeline: TranslationPipeline, held: HeldTurn, outcome: list):
    """Start ``resolve`` while the turn lock is taken: the turn is claimed, the lock not."""
    pipeline._turn_lock.acquire()
    resolving = threading.Thread(target=lambda: outcome.append(pipeline.resolve(held, DE)))
    resolving.start()
    for _ in range(200):
        if pipeline.held_turns() == ():
            break
        threading.Event().wait(0.01)
    assert pipeline.held_turns() == ()  # claimed: no longer held, not discardable
    return resolving


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


def gated_queue_class(taken: threading.Event, release: threading.Event):
    """A runner queue whose first ``get`` of an item pauses after taking it."""
    import queue as queue_module

    class GatedQueue(queue_module.Queue):
        def get(self, block=True, timeout=None):
            item = super().get(block, timeout)
            if item is not None and not taken.is_set():
                taken.set()
                assert release.wait(timeout=5.0)
            return item

    return GatedQueue


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


def test_a_failed_resolution_without_stop_is_held_again() -> None:
    class FailingForcedRecognizer(FakeRecognizer):
        def transcribe(self, samples, sample_rate, language=None):
            if language is not None:
                raise RuntimeError("model failed")
            return super().transcribe(samples, sample_rate, language)

    pipeline = TranslationPipeline(
        FailingForcedRecognizer(detected="en"), FakeTranslator(), None, None
    )
    held = pipeline.process(bound())

    with pytest.raises(RuntimeError):
        pipeline.resolve(held, DE)

    assert pipeline.held_turns() == (held,)
