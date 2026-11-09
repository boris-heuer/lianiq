"""Fakes and builders shared by the pipeline and runner tests (``test_pipeline*.py``)."""

from __future__ import annotations

import threading

import numpy as np

from lianiq.conversation.routing import HeldTurn
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
from lianiq.pipeline import BoundUtterance, TranslationPipeline, bind_utterance

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
