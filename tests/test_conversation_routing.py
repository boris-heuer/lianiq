"""Pair-scoped turn routing (CAP-0169 AC-10, AC-12; contract.md §3.1.5).

The five scenario sets are the regression oracle of the previous enum router: every
turn is routed on its own detected language, never by assumed speaker alternation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

import numpy as np
import pytest

from lianiq.conversation.routing import HeldTurn, TurnRoute, TurnRouter
from lianiq.domain import AudioUtterance, Transcript
from lianiq.languages import (
    BUILTIN_REGISTRY,
    InputKind,
    LanguageId,
    OutputKind,
    RoutingKind,
    SessionPair,
    UsageMode,
)
from lianiq.pipeline import PipelineRunner, TranslationPipeline, bind_utterance
from tests.languages.synthetic import QAA, QAB, synthetic_registry

DE = LanguageId("de")
ZH = LanguageId("zh-Hans")
PAIR = BUILTIN_REGISTRY.pair(DE, ZH)
AUTOMATIC = SessionPair(
    PAIR, UsageMode(InputKind.MICROPHONE, RoutingKind.BIDIRECTIONAL, OutputKind.TEXT)
)


def fixed(source: LanguageId, pair=PAIR) -> SessionPair:
    return SessionPair(
        pair,
        UsageMode(InputKind.MICROPHONE, RoutingKind.FIXED, OutputKind.TEXT),
        fixed_source=source,
    )


def transcript(language: str | None, probability: float = 0.99, code: str = "") -> Transcript:
    return Transcript(
        "text", None if language is None else LanguageId(language), probability, 1.0, code
    )


@dataclass(frozen=True, slots=True)
class SyntheticTurn:
    speaker: str
    text: str
    detected_language: LanguageId
    expected_target: LanguageId


SCENARIOS = {
    "alternating_two_participants": (
        SyntheticTurn("A", "Guten Tag", DE, ZH),
        SyntheticTurn("B", "您好", ZH, DE),
        SyntheticTurn("A", "Wie geht es Ihnen?", DE, ZH),
    ),
    "consecutive_german_turns": (
        SyntheticTurn("A", "Ich habe zwei Fragen.", DE, ZH),
        SyntheticTurn("A", "Die erste betrifft den Termin.", DE, ZH),
        SyntheticTurn("C", "Die zweite betrifft den Preis.", DE, ZH),
    ),
    "consecutive_mandarin_turns": (
        SyntheticTurn("B", "我有两个问题。", ZH, DE),
        SyntheticTurn("B", "第一个问题关于日期。", ZH, DE),
        SyntheticTurn("D", "第二个问题关于价格。", ZH, DE),
    ),
    "three_participant_mixed_conversation": (
        SyntheticTurn("A", "Willkommen.", DE, ZH),
        SyntheticTurn("B", "谢谢。", ZH, DE),
        SyntheticTurn("C", "Wir beginnen jetzt.", DE, ZH),
        SyntheticTurn("B", "好的。", ZH, DE),
    ),
    "short_acknowledgements": (
        SyntheticTurn("A", "Ja.", DE, ZH),
        SyntheticTurn("A", "Genau.", DE, ZH),
        SyntheticTurn("B", "嗯。", ZH, DE),
        SyntheticTurn("B", "对。", ZH, DE),
    ),
}


@pytest.mark.parametrize("turns", SCENARIOS.values(), ids=SCENARIOS.keys())
def test_automatic_routes_every_turn_independently(turns: tuple[SyntheticTurn, ...]) -> None:
    router = TurnRouter(0.7)

    routes = [router.route(AUTOMATIC, transcript(turn.detected_language)) for turn in turns]

    assert routes == [TurnRoute(turn.detected_language, turn.expected_target) for turn in turns]


@pytest.mark.parametrize(
    ("source", "detected", "expected"),
    [(DE, ZH, TurnRoute(DE, ZH)), (ZH, DE, TurnRoute(ZH, DE)), (ZH, None, TurnRoute(ZH, DE))],
)
def test_fixed_routing_ignores_detection(source, detected, expected) -> None:
    # Even an unregistered or low-confidence detection never holds a fixed-routing turn.
    assert TurnRouter(0.7).route(fixed(source), transcript(detected, 0.1)) == expected


@pytest.mark.parametrize(
    ("detected", "probability", "code", "reason"),
    [
        ("en", 0.99, "en", "out_of_pair"),  # registered but planned and outside the pair
        (None, 0.99, "ja", "unregistered"),
        ("de", 0.69, "de", "low_confidence"),
        ("zh-Hans", 0.0, "zh", "low_confidence"),
    ],
)
def test_automatic_holds_unclear_turns(detected, probability, code, reason) -> None:
    turn_id = uuid4()
    captured_at = datetime.now().astimezone()
    detected_transcript = transcript(detected, probability, code)

    held = TurnRouter(0.7).route(
        AUTOMATIC, detected_transcript, turn_id=turn_id, captured_at=captured_at
    )

    assert held == HeldTurn(turn_id, captured_at, detected_transcript, reason)


def test_minimum_probability_is_inclusive() -> None:
    assert TurnRouter(0.7).route(AUTOMATIC, transcript("de", 0.70)) == TurnRoute(DE, ZH)


def test_router_is_scoped_to_the_session_pair() -> None:
    synthetic = synthetic_registry().pair(QAA, QAB)
    session = SessionPair(synthetic, AUTOMATIC.mode)
    router = TurnRouter(0.7)

    assert router.route(session, transcript("qab")) == TurnRoute(QAB, QAA)
    assert isinstance(router.route(session, transcript("de")), HeldTurn)  # not in this pair


def test_router_rejects_an_invalid_threshold() -> None:
    with pytest.raises(ValueError, match="between 0 and 1"):
        TurnRouter(1.5)


class SequenceRecognizer:
    def __init__(self, turns) -> None:
        self.pending = iter(turns)
        self.calls: list[str | None] = []

    def transcribe(self, samples, sample_rate, language=None):
        self.calls.append(language)
        turn = next(self.pending)
        return Transcript(turn.text, turn.detected_language, 0.99, len(samples) / sample_rate)


class RecordingTranslator:
    def __init__(self) -> None:
        self.calls = []

    def translate(self, text, edge, context=()):
        self.calls.append((text, edge.key, context))
        return f"{edge.target}:{text}"


AUDIO = AudioUtterance(np.zeros(4_000, dtype=np.float32), 16_000)


@pytest.mark.parametrize("turns", SCENARIOS.values(), ids=SCENARIOS.keys())
def test_ac10_pipeline_routes_each_turn_to_the_other_pair_member(
    turns: tuple[SyntheticTurn, ...],
) -> None:
    translator = RecordingTranslator()
    pipeline = TranslationPipeline(SequenceRecognizer(turns), translator, None, None)

    results = [pipeline.process(bind_utterance(AUDIO, AUTOMATIC)) for _turn in turns]

    assert [(r.source_language, r.target_language) for r in results] == [
        (turn.detected_language, turn.expected_target) for turn in turns
    ]
    assert [call[:2] for call in translator.calls] == [
        (turn.text, f"{turn.detected_language}>{turn.expected_target}") for turn in turns
    ]


@pytest.mark.parametrize("turns", SCENARIOS.values(), ids=SCENARIOS.keys())
def test_ac10_runner_preserves_order_and_routes_every_turn(
    turns: tuple[SyntheticTurn, ...],
) -> None:
    recognizer = SequenceRecognizer(turns)
    pipeline = TranslationPipeline(recognizer, RecordingTranslator(), None, None)
    results, errors = [], []
    runner = PipelineRunner(pipeline, on_result=results.append, on_error=errors.append)
    runner.start(AUTOMATIC)
    for _turn in turns:
        runner.submit(AUDIO)
        runner._queue.join()  # one at a time, so the bounded backlog never drops a turn

    assert runner.stop() == 0
    assert errors == []
    assert recognizer.calls == [None] * len(turns)  # Automatic always detects
    assert [(r.source_language, r.target_language) for r in results] == [
        (turn.detected_language, turn.expected_target) for turn in turns
    ]
    assert [r.captured_at for r in results] == sorted(r.captured_at for r in results)


def test_ac12_fixed_source_forces_the_recogniser_and_never_holds() -> None:
    class DetectingEnglish:
        def __init__(self) -> None:
            self.calls: list[str | None] = []

        def transcribe(self, samples, sample_rate, language=None):
            self.calls.append(language)
            # A recogniser reporting a foreign, uncertain language is ignored under FIXED.
            return Transcript("你好", LanguageId("en"), 0.2, 1.0, "en")

    recognizer = DetectingEnglish()
    translator = RecordingTranslator()
    pipeline = TranslationPipeline(recognizer, translator, None, None)
    results, held, errors = [], [], []
    runner = PipelineRunner(
        pipeline, on_result=results.append, on_error=errors.append, on_held=held.append
    )
    runner.start(fixed(ZH))
    runner.submit(AUDIO)
    runner._queue.join()
    runner.submit(AUDIO)

    assert runner.stop() == 0
    assert recognizer.calls == ["zh-Hans", "zh-Hans"]
    assert held == [] and errors == []
    assert pipeline.held_turns() == ()
    assert [(r.source_language, r.target_language) for r in results] == [(ZH, DE)] * 2
    assert [call[1] for call in translator.calls] == ["zh-Hans>de"] * 2
