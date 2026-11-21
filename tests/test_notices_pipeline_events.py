"""The ``pipeline.py`` notice events (CAP-0168 WI-03): overflow, dropped turns, playback failure.

Split from ``test_notices.py``; the pipeline fakes are in ``tests/_pipeline_helpers.py``.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from lianiq.conversation.spoken_output import SpokenOutput
from lianiq.languages import LanguageId
from lianiq.pipeline import PipelineEventKind, PipelineRunner, TranslationPipeline
from lianiq.tts.voice_controls import VoiceOptions
from tests._pipeline_helpers import (
    AUTOMATIC,
    FakeRecognizer,
    FakeTranslator,
    RecordingPipeline,
    bound,
    utterance,
)

ZH = LanguageId("zh-Hans")


def test_runner_reports_overflow_as_a_notice_event_instead_of_text() -> None:
    release = threading.Event()
    pipeline = RecordingPipeline(release)
    events, errors = [], []
    runner = PipelineRunner(
        pipeline, on_result=lambda _r: None, on_error=errors.append, on_event=events.append
    )
    runner.start(AUTOMATIC)
    runner.submit(utterance())
    assert pipeline.started.wait(timeout=1.0)
    for _ in range(3):  # two fit the queue, the third drops the oldest
        runner.submit(utterance())
    release.set()
    runner.stop(timeout=5.0)

    assert [event.kind for event in events] == [PipelineEventKind.QUEUE_OVERFLOW]
    assert errors == []


def test_runner_reports_dropped_turns_at_stop_as_a_notice_event() -> None:
    release = threading.Event()
    pipeline = RecordingPipeline(release)
    events, errors = [], []
    runner = PipelineRunner(
        pipeline, on_result=lambda _r: None, on_error=errors.append, on_event=events.append
    )
    runner.start(AUTOMATIC)
    runner.submit(utterance())
    assert pipeline.started.wait(timeout=1.0)
    runner.submit(utterance())
    runner.submit(utterance())

    assert runner.stop(timeout=0.2) == 2
    release.set()
    runner._thread.join(timeout=2.0)
    assert [(event.kind, event.count) for event in events] == [(PipelineEventKind.TURNS_DROPPED, 2)]
    assert errors == []


class FileSynthesizer:
    def __init__(self, folder: Path) -> None:
        self.folder = folder

    def synthesize(self, text, language):
        path = self.folder / f"{language}.wav"
        path.write_bytes(b"RIFF")
        return path


def failing_playback(_path, _device) -> None:
    raise RuntimeError("PortAudio error: device unavailable")


def spoken_output(folder: Path, play, events: list) -> SpokenOutput:
    return SpokenOutput(
        lambda: FileSynthesizer(folder),
        play,
        lambda: None,
        lambda _language: VoiceOptions(),
        lambda _state: None,
        events.append,
    )


def test_playback_failure_keeps_the_text_result_and_stops_spoken_output(tmp_path) -> None:
    pipeline = TranslationPipeline(FakeRecognizer(), FakeTranslator())
    events = []
    pipeline.spoken = spoken_output(tmp_path, failing_playback, events)
    pipeline.spoken.open(frozenset({ZH}), None)
    pipeline.set_spoken_languages(frozenset({ZH}))
    results = []
    runner = PipelineRunner(pipeline, on_result=results.append, on_error=pytest.fail)
    runner.start(AUTOMATIC)
    runner.submit(utterance())
    runner.stop(timeout=5.0)

    assert [result.translated_text for result in results] == ["您好"]  # the turn stays as text
    assert pipeline.spoken.plan == frozenset()  # the session continues text-only
    assert [(event.kind, event.language) for event in events] == [
        (PipelineEventKind.PLAYBACK_FAILED, ZH)
    ]
    assert events[0].message == "RuntimeError"  # the error class only (CAP-0167 AC-23)
    assert list(tmp_path.iterdir()) == []  # the synthesized file is still removed


def test_processing_a_turn_never_synthesizes(tmp_path) -> None:
    pipeline = TranslationPipeline(
        FakeRecognizer(), FakeTranslator(), FileSynthesizer(tmp_path), failing_playback
    )
    pipeline.set_spoken_languages(frozenset({ZH}))

    result = pipeline.process(bound())

    assert result is not None and result.translated_text == "您好"
    assert list(tmp_path.iterdir()) == []  # speaking is the runner's step after the result
