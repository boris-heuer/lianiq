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
