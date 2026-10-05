from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pytest

from offline_translator.conversation.routing import TurnRouter
from offline_translator.domain import AudioUtterance, ConversationMode, Language, Transcript
from offline_translator.pipeline import TranslationPipeline


@dataclass(frozen=True, slots=True)
class SyntheticTurn:
    speaker: str
    text: str
    detected_language: Language
    expected_target: Language


SCENARIOS = {
    "alternating_two_participants": (
        SyntheticTurn("A", "Guten Tag", Language.GERMAN, Language.MANDARIN),
        SyntheticTurn("B", "您好", Language.MANDARIN, Language.GERMAN),
        SyntheticTurn("A", "Wie geht es Ihnen?", Language.GERMAN, Language.MANDARIN),
    ),
    "consecutive_german_turns": (
        SyntheticTurn("A", "Ich habe zwei Fragen.", Language.GERMAN, Language.MANDARIN),
        SyntheticTurn("A", "Die erste betrifft den Termin.", Language.GERMAN, Language.MANDARIN),
        SyntheticTurn("C", "Die zweite betrifft den Preis.", Language.GERMAN, Language.MANDARIN),
    ),
    "consecutive_mandarin_turns": (
        SyntheticTurn("B", "我有两个问题。", Language.MANDARIN, Language.GERMAN),
        SyntheticTurn("B", "第一个问题关于日期。", Language.MANDARIN, Language.GERMAN),
        SyntheticTurn("D", "第二个问题关于价格。", Language.MANDARIN, Language.GERMAN),
    ),
    "three_participant_mixed_conversation": (
        SyntheticTurn("A", "Willkommen.", Language.GERMAN, Language.MANDARIN),
        SyntheticTurn("B", "谢谢。", Language.MANDARIN, Language.GERMAN),
        SyntheticTurn("C", "Wir beginnen jetzt.", Language.GERMAN, Language.MANDARIN),
        SyntheticTurn("B", "好的。", Language.MANDARIN, Language.GERMAN),
    ),
    "short_acknowledgements": (
        SyntheticTurn("A", "Ja.", Language.GERMAN, Language.MANDARIN),
        SyntheticTurn("A", "Genau.", Language.GERMAN, Language.MANDARIN),
        SyntheticTurn("B", "嗯。", Language.MANDARIN, Language.GERMAN),
        SyntheticTurn("B", "对。", Language.MANDARIN, Language.GERMAN),
    ),
}


@pytest.mark.parametrize("turns", SCENARIOS.values(), ids=SCENARIOS.keys())
def test_auto_mode_routes_every_turn_independently(turns: tuple[SyntheticTurn, ...]) -> None:
    router = TurnRouter()

    routes = [router.route(ConversationMode.AUTO, turn.detected_language) for turn in turns]

    assert [route.source for route in routes] == [turn.detected_language for turn in turns]
    assert [route.target for route in routes] == [turn.expected_target for turn in turns]


@pytest.mark.parametrize(
    ("mode", "detected", "expected_source"),
    [
        (ConversationMode.DE_TO_ZH, Language.MANDARIN, Language.GERMAN),
        (ConversationMode.ZH_TO_DE, Language.GERMAN, Language.MANDARIN),
    ],
)
def test_manual_mode_overrides_detection(mode, detected, expected_source) -> None:
    route = TurnRouter().route(mode, detected)

    assert route.source is expected_source
    assert route.target is expected_source.other


@pytest.mark.parametrize("turns", SCENARIOS.values(), ids=SCENARIOS.keys())
def test_pipeline_preserves_order_for_synthetic_conversations(
    turns: tuple[SyntheticTurn, ...],
) -> None:
    pending = iter(turns)

    class SequenceRecognizer:
        def transcribe(self, samples, sample_rate, language=None):
            turn = next(pending)
            return Transcript(turn.text, turn.detected_language, 0.99, len(samples) / sample_rate)

    class RecordingTranslator:
        def __init__(self) -> None:
            self.calls = []

        def translate(self, text, source, target, context=()):
            self.calls.append((text, source, target, context))
            return f"{target.value}:{text}"

    translator = RecordingTranslator()
    pipeline = TranslationPipeline(SequenceRecognizer(), translator, None, None)
    audio = AudioUtterance(np.zeros(4_000, dtype=np.float32), 16_000)

    results = [pipeline.process(audio, ConversationMode.AUTO) for _turn in turns]

    assert all(result is not None for result in results)
    assert [result.source_language for result in results if result] == [
        turn.detected_language for turn in turns
    ]
    assert [result.target_language for result in results if result] == [
        turn.expected_target for turn in turns
    ]
    assert [call[0] for call in translator.calls] == [turn.text for turn in turns]
