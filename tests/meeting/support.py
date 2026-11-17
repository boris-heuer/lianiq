"""Shared meeting test data: a fake clock, endpoints and the de/zh-Hans pair (CAP-0177).

WI-03 adds the synthetic capture/render adapters and spy engines of the controller tests:
speech blocks carry a numeric tag in their amplitude, ``ScriptedRecognizer`` decodes it and
answers from a script, and ``SyntheticRenders`` stands in for the device behind every
``EndpointPlaybackStream`` (``play_pcm``) and records what each render endpoint played.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import numpy as np

from lianiq.call_bridge.contracts import AudioEndpointRef, EndpointFlow
from lianiq.config import AudioConfig
from lianiq.domain import Transcript
from lianiq.languages import BUILTIN_REGISTRY, LanguageId, LanguagePair

DE = LanguageId("de")
ZH = LanguageId("zh-Hans")
DE_ZH: LanguagePair = BUILTIN_REGISTRY.pair(DE, ZH)


class FakeClock:
    """A monotonic clock in seconds that only moves when a test advances it."""

    def __init__(self, start: float = 100.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance_ms(self, milliseconds: float) -> None:
        self.now += milliseconds / 1000.0


def endpoint(
    name: str,
    flow: EndpointFlow,
    endpoint_id: str | None = None,
    runtime_index: int = 0,
    sample_rate: int = 48_000,
) -> AudioEndpointRef:
    return AudioEndpointRef(
        endpoint_id=endpoint_id or f"{flow.value}:{name}",
        display_name=name,
        flow=flow,
        host_api="Windows WASAPI",
        runtime_index=runtime_index,
        sample_rate=sample_rate,
    )


def capture(name: str, endpoint_id: str | None = None) -> AudioEndpointRef:
    return endpoint(name, EndpointFlow.CAPTURE, endpoint_id)


def render(name: str, endpoint_id: str | None = None) -> AudioEndpointRef:
    return endpoint(name, EndpointFlow.RENDER, endpoint_id)


# --- WI-03 synthetic adapters and spy engines ----------------------------------------------

# 30 ms blocks at 16 kHz; a pause of three silent blocks (90 ms) ends a contribution.
AUDIO = AudioConfig(
    chunk_ms=30, start_rms=0.02, end_silence_ms=90, pre_roll_ms=30, min_speech_ms=60
)
BLOCK = AUDIO.sample_rate * AUDIO.chunk_ms // 1000
TABLE_MIC, TABLE_SPEAKER, USER_MIC, LOCAL_OUTPUT = 1, 2, 3, 4  # runtime indices


def speech(tag: int, blocks: int = 4) -> list[np.ndarray]:
    """Voiced blocks whose amplitude encodes ``tag`` (0..900)."""
    return [np.full(BLOCK, 0.05 + tag / 1000, dtype=np.float32) for _ in range(blocks)]


def pause(blocks: int = 3) -> list[np.ndarray]:
    return [np.zeros(BLOCK, dtype=np.float32) for _ in range(blocks)]


def tag_of(samples: np.ndarray) -> int:
    return round((float(np.max(np.abs(samples))) - 0.05) * 1000)


def feed(controller, role, blocks) -> None:
    """Push blocks through one input's segmenter, as its capture thread does."""
    for block in blocks:
        controller.captures[role].process_block(block)


def say(controller, role, tag: int) -> None:
    feed(controller, role, [*speech(tag), *pause()])


@dataclass
class Line:
    """One scripted contribution: the detection result and the forced-pass text."""

    language: LanguageId | None
    text: str
    probability: float = 0.95
    forced_text: str | None = None


@dataclass
class ScriptedRecognizer:
    """Answers by the tag decoded from the samples; records ``(tag, language)`` per call."""

    script: dict[int, Line] = field(default_factory=dict)
    calls: list[tuple[int, LanguageId | None]] = field(default_factory=list)
    hold: threading.Event | None = None  # the first call waits until this event is set

    def transcribe(self, samples, sample_rate: int, language: LanguageId | None = None):
        if self.hold is not None:
            hold, self.hold = self.hold, None
            hold.wait(10.0)
        tag = tag_of(samples)
        self.calls.append((tag, language))
        line = self.script[tag]
        if language is None:
            return Transcript(line.text, line.language, line.probability, 1.0)
        return Transcript(line.forced_text or line.text, language, 1.0, 1.0)


@dataclass
class PcmSynthesizer:
    """In-memory synthesis spy: the samples carry the 1-based call number; no file is written."""

    calls: list[tuple[str, LanguageId]] = field(default_factory=list)
    sample_rate: int = 22_050

    def synthesize_pcm(self, text: str, language: LanguageId) -> tuple[np.ndarray, int]:
        self.calls.append((text, language))
        return np.full(160, len(self.calls), dtype=np.int16), self.sample_rate


@dataclass(frozen=True)
class Played:
    runtime_index: int
    language: LanguageId  # the language the played samples were synthesised in


class SyntheticRenders:
    """Replaces ``play_pcm`` behind every ``EndpointPlaybackStream``.

    ``during(runtime_index)`` runs while the audio "plays"; ``gate`` holds each playback
    until it is set.
    """

    def __init__(self, synthesizer: PcmSynthesizer) -> None:
        self.synthesizer = synthesizer
        self.played: list[Played] = []
        self.during = None
        self.gate: threading.Event | None = None

    def __call__(self, samples, sample_rate: int, output_device: int | None = None) -> None:
        assert sample_rate == self.synthesizer.sample_rate
        index = int(samples[0]) - 1
        self.played.append(Played(output_device, self.synthesizer.calls[index][1]))
        if self.during is not None:
            self.during(output_device)
        if self.gate is not None:
            self.gate.wait(10.0)


class NullStream:
    """A capture stream that opens nothing; it keeps the audio callback for tests."""

    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.callback = kwargs["callback"]
        self.started = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.started = False

    def close(self) -> None:
        return None


class SyntheticStreams:
    """A ``stream_factory`` that records every capture stream it opened."""

    def __init__(self) -> None:
        self.created: list[NullStream] = []

    def __call__(self, **kwargs) -> NullStream:
        stream = NullStream(**kwargs)
        self.created.append(stream)
        return stream

    def device(self, runtime_index: int) -> NullStream:
        return next(s for s in reversed(self.created) if s.kwargs["device"] == runtime_index)


class WallClock:
    """Speech-end timestamps that advance by ``step_ms`` per contribution."""

    def __init__(self, step_ms: float = 400.0) -> None:
        self.now = datetime(2026, 11, 17, 10, 0, tzinfo=timezone(timedelta(hours=1)))
        self.step = timedelta(milliseconds=step_ms)
        self._lock = threading.Lock()

    def __call__(self) -> datetime:
        with self._lock:
            self.now += self.step
            return self.now


class Events:
    """Collects published ``MeetingEvent``s from any thread."""

    def __init__(self) -> None:
        self.items: list = []
        self._lock = threading.Lock()

    def __call__(self, event) -> None:
        with self._lock:
            self.items.append(event)

    def of(self, kind) -> list:
        with self._lock:
            return [event for event in self.items if event.kind is kind]


def wait_until(predicate, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return bool(predicate())
