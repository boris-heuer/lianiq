from __future__ import annotations

import threading
import time
from pathlib import Path

import numpy as np
import pytest

from lianiq.call_bridge.contracts import BridgeEventKind, LaneId
from lianiq.call_bridge.inference_scheduler import InferenceScheduler
from lianiq.call_bridge.translation_lane import TranslationLane
from lianiq.domain import AudioUtterance, Transcript
from lianiq.languages.capabilities import DirectedEdge
from lianiq.languages.registry import LanguageId

GERMAN = LanguageId("de")
MANDARIN = LanguageId("zh-Hans")
DE_ZH = DirectedEdge(GERMAN, MANDARIN)
ZH_DE = DirectedEdge(MANDARIN, GERMAN)


class Recognizer:
    def transcribe(self, samples, sample_rate, language=None):
        marker = str(int(samples[0]))
        return Transcript(marker, language, 1.0, len(samples) / sample_rate)


class Translator:
    def translate(self, text, edge, context=()):
        return f"{edge.target}:{text}"


class Synthesizer:
    def synthesize(self, text, language):
        return Path(f"{language}-{text}.wav")


def utterance(marker: int) -> AudioUtterance:
    return AudioUtterance(np.full(160, marker, dtype=np.float32), 16_000)


def test_lane_has_fixed_direction_and_preserves_order() -> None:
    played: list[str] = []
    results = []
    lane = TranslationLane(
        lane_id=LaneId.OUTBOUND,
        edge=DE_ZH,
        recognizer=Recognizer(),
        translator=Translator(),
        synthesizer=Synthesizer(),
        playback=lambda path: played.append(path.name),
        scheduler=InferenceScheduler(max_concurrent=1),
        on_result=results.append,
    )

    lane.start()
    lane.submit(utterance(1))
    lane.submit(utterance(2))
    assert lane.wait_until_idle(timeout=1.0)
    assert lane.stop(timeout=1.0)

    assert [result.source_text for result in results] == ["1", "2"]
    assert [result.source_language for result in results] == [GERMAN] * 2
    assert played == ["zh-Hans-zh-Hans:1.wav", "zh-Hans-zh-Hans:2.wav"]


def test_failed_synthesis_never_reaches_playback() -> None:
    events = []
    played = []

    class FailingSynthesizer:
        def synthesize(self, text, language):
            raise RuntimeError("tts unavailable")

    lane = TranslationLane(
        lane_id=LaneId.INBOUND,
        edge=ZH_DE,
        recognizer=Recognizer(),
        translator=Translator(),
        synthesizer=FailingSynthesizer(),
        playback=played.append,
        scheduler=InferenceScheduler(max_concurrent=1),
        on_event=events.append,
    )
    lane.start()
    lane.submit(utterance(1))
    assert lane.wait_until_idle(timeout=1.0)
    lane.stop(timeout=1.0)

    assert played == []
    assert any(
        event.kind is BridgeEventKind.ERROR and event.category == "tts_failure" for event in events
    )
    assert all("tts unavailable" not in event.message for event in events)


def test_playback_failure_is_sanitized_and_classified_for_endpoint_muting() -> None:
    events = []

    def fail_playback(_path):
        raise RuntimeError(r"C:\\Users\\private\\device failed")

    lane = TranslationLane(
        lane_id=LaneId.OUTBOUND,
        edge=DE_ZH,
        recognizer=Recognizer(),
        translator=Translator(),
        synthesizer=Synthesizer(),
        playback=fail_playback,
        scheduler=InferenceScheduler(max_concurrent=1),
        on_event=events.append,
    )
    lane.start()
    lane.submit(utterance(1))
    assert lane.wait_until_idle(timeout=1.0)
    lane.stop(timeout=1.0)

    errors = [event for event in events if event.kind is BridgeEventKind.ERROR]
    assert [event.category for event in errors] == ["playback_failure"]
    assert all("private" not in event.message for event in errors)


def test_stale_and_overflow_work_is_dropped_and_reported() -> None:
    release = threading.Event()
    events = []

    class BlockingRecognizer(Recognizer):
        def transcribe(self, samples, sample_rate, language=None):
            release.wait(timeout=1.0)
            return super().transcribe(samples, sample_rate, language)

    lane = TranslationLane(
        lane_id=LaneId.OUTBOUND,
        edge=DE_ZH,
        recognizer=BlockingRecognizer(),
        translator=Translator(),
        synthesizer=Synthesizer(),
        playback=lambda _path: None,
        scheduler=InferenceScheduler(max_concurrent=1),
        max_pending_age_ms=5,
        queue_size=2,
        on_event=events.append,
    )
    lane.start()
    lane.submit(utterance(1))
    lane.submit(utterance(2))
    lane.submit(utterance(3))
    lane.submit(utterance(4))
    time.sleep(0.02)
    release.set()
    assert lane.wait_until_idle(timeout=1.0)
    lane.stop(timeout=1.0)

    assert sum(event.kind is BridgeEventKind.DROPPED for event in events) >= 2


def test_stop_during_inference_mutes_late_output() -> None:
    started = threading.Event()
    release = threading.Event()
    played = []

    class BlockingRecognizer(Recognizer):
        def transcribe(self, samples, sample_rate, language=None):
            started.set()
            release.wait(timeout=1.0)
            return super().transcribe(samples, sample_rate, language)

    lane = TranslationLane(
        lane_id=LaneId.OUTBOUND,
        edge=DE_ZH,
        recognizer=BlockingRecognizer(),
        translator=Translator(),
        synthesizer=Synthesizer(),
        playback=played.append,
        scheduler=InferenceScheduler(max_concurrent=1),
    )
    lane.start()
    lane.submit(utterance(1))
    assert started.wait(timeout=1.0)

    assert lane.stop(timeout=0.01) is False
    release.set()
    deadline = time.monotonic() + 1.0
    while lane.running and time.monotonic() < deadline:
        time.sleep(0.005)
    assert lane.stop(timeout=1.0) is True

    assert played == []


def test_ac09_lane_edge_is_fixed_and_used_for_every_turn() -> None:
    edges = []

    class RecordingTranslator(Translator):
        def translate(self, text, edge, context=()):
            edges.append(edge)
            return super().translate(text, edge, context)

    lane = TranslationLane(
        LaneId.INBOUND,
        ZH_DE,
        Recognizer(),
        RecordingTranslator(),
        Synthesizer(),
        lambda _path: None,
        InferenceScheduler(max_concurrent=1),
    )
    with pytest.raises(AttributeError):
        lane.edge = DE_ZH  # type: ignore[misc]

    lane.start()
    lane.submit(utterance(1))
    lane.submit(utterance(2))
    assert lane.wait_until_idle(timeout=1.0)
    assert lane.stop(timeout=1.0)

    assert edges == [ZH_DE, ZH_DE]
    assert (lane.source_language, lane.target_language) == (MANDARIN, GERMAN)


def test_lane_requires_a_directed_edge() -> None:
    with pytest.raises(TypeError, match="DirectedEdge"):
        TranslationLane(
            LaneId.OUTBOUND,
            (GERMAN, MANDARIN),  # type: ignore[arg-type]
            Recognizer(),
            Translator(),
            Synthesizer(),
            lambda _path: None,
            InferenceScheduler(max_concurrent=1),
        )
