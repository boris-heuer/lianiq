"""TranslationPipeline routing, held turns and their resolution.

The runner tests are in ``test_pipeline_runner.py``, the stop races in
``test_pipeline_stop_races.py``; the shared fakes are in ``tests/_pipeline_helpers.py``.
"""

from __future__ import annotations

import dataclasses

import pytest

from lianiq.conversation.routing import HeldTurn
from lianiq.domain import Transcript
from lianiq.languages import LanguageId, UnsupportedModeError
from lianiq.pipeline import TranslationPipeline
from tests._pipeline_helpers import DE, ZH, ZH_TO_DE, FakeRecognizer, FakeTranslator, bound


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
