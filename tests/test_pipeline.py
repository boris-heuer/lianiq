from __future__ import annotations

import threading

import numpy as np
import pytest

from lianiq.domain import (
    AudioUtterance,
    ConversationMode,
    Language,
    Transcript,
)
from lianiq.languages import LanguageId
from lianiq.pipeline import PipelineRunner, TranslationPipeline, UnroutedTurnError


class FakeRecognizer:
    def __init__(self, detected: str | None = "de", text: str = "Guten Tag", code="") -> None:
        self.detected = None if detected is None else LanguageId(detected)
        self.text = text
        self.code = code
        self.received_language = None

    def transcribe(self, samples, sample_rate, language=None):
        self.received_language = language
        detected = language or self.detected
        return Transcript(self.text, detected, 0.99, len(samples) / sample_rate, self.code)


class FakeTranslator:
    def __init__(self) -> None:
        self.calls = []

    def translate(self, text, edge, context=()):
        self.calls.append((text, edge.key, context))
        return "您好" if edge.target == "zh-Hans" else "Guten Tag"


def utterance() -> AudioUtterance:
    return AudioUtterance(np.zeros(16_000, dtype=np.float32), 16_000)


def test_auto_mode_uses_detected_direction() -> None:
    recognizer = FakeRecognizer()
    translator = FakeTranslator()
    pipeline = TranslationPipeline(recognizer, translator, None, None)
    result = pipeline.process(utterance(), ConversationMode.AUTO)
    assert result is not None
    assert result.source_language is Language.GERMAN
    assert result.target_language is Language.MANDARIN
    assert recognizer.received_language is None
    assert translator.calls == [("Guten Tag", "de>zh-Hans", ())]


def test_manual_mode_forces_whisper_language() -> None:
    recognizer = FakeRecognizer(detected="de", text="你好")
    translator = FakeTranslator()
    pipeline = TranslationPipeline(recognizer, translator, None, None)
    result = pipeline.process(utterance(), ConversationMode.ZH_TO_DE)
    assert result is not None
    assert recognizer.received_language == "zh-Hans"
    assert result.target_language is Language.GERMAN
    assert translator.calls[0][1] == "zh-Hans>de"


@pytest.mark.parametrize(("detected", "code"), [("en", "en"), (None, "ja")])
def test_auto_mode_never_guesses_an_unsupported_detected_language(detected, code) -> None:
    translator = FakeTranslator()
    pipeline = TranslationPipeline(
        FakeRecognizer(detected=detected, text="您好", code=code), translator, None, None
    )

    with pytest.raises(UnroutedTurnError, match=code):
        pipeline.process(utterance(), ConversationMode.AUTO)

    assert translator.calls == []


def test_empty_transcript_is_ignored() -> None:
    pipeline = TranslationPipeline(FakeRecognizer(text="  "), FakeTranslator(), None, None)
    assert pipeline.process(utterance(), ConversationMode.AUTO) is None


def test_runner_waits_for_active_processing_during_stop() -> None:
    started = threading.Event()
    release = threading.Event()

    class BlockingPipeline:
        def process(self, _utterance, _mode):
            started.set()
            release.wait(timeout=1.0)

    runner = PipelineRunner(
        BlockingPipeline(),
        mode_provider=lambda: ConversationMode.AUTO,
        on_result=lambda _result: None,
        on_error=lambda _message: None,
    )
    runner.start()
    runner.submit(utterance())
    assert started.wait(timeout=1.0)
    threading.Timer(0.05, release.set).start()

    runner.stop(timeout=1.0)

    assert runner._thread is None
