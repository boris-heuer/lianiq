"""Pipeline adapter protocols, bound turns and notice events (moved from ``pipeline.py``)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Protocol
from uuid import UUID, uuid4

import numpy as np

from lianiq.conversation.routing import HeldTurn
from lianiq.domain import AudioUtterance, Transcript
from lianiq.languages.capabilities import DirectedEdge
from lianiq.languages.errors import CapabilityMissingError
from lianiq.languages.modes import SessionPair
from lianiq.languages.registry import LanguageId


# Adapter protocols (CAP-0169 contract.md §3.1.6): every adapter is keyed by language ID
# or directed edge and raises ``CapabilityMissingError`` for an unconfigured one.
class SpeechRecognizer(Protocol):
    def transcribe(
        self, samples: np.ndarray, sample_rate: int, language: LanguageId | None = None
    ) -> Transcript: ...


class Translator(Protocol):
    def translate(self, text: str, edge: DirectedEdge, context: tuple[str, ...] = ()) -> str: ...


class Synthesizer(Protocol):
    def synthesize(self, text: str, language: LanguageId) -> Path: ...


class PcmSynthesizer(Protocol):
    """In-memory synthesis (CAP-0177 meeting): PCM16 mono samples and rate, no file."""

    def synthesize_pcm(self, text: str, language: LanguageId) -> tuple[np.ndarray, int]: ...


@dataclass(frozen=True, slots=True)
class AdapterFactories:
    """Adapter constructors, each called at most once and only when a mode requires it."""

    recognizer: Callable[[], SpeechRecognizer] | None = None
    translator: Callable[[], Translator] | None = None
    synthesizer: Callable[[], Synthesizer] | None = None


@dataclass(frozen=True, slots=True)
class BoundUtterance:
    """A captured utterance bound to the session pair it was captured under.

    The worker routes and translates it with this binding, never with a live selection,
    so a queued turn keeps its languages when the session stops or the pair changes.
    """

    utterance: AudioUtterance
    session: SessionPair
    turn_id: UUID
    captured_at: datetime


def bind_utterance(utterance: AudioUtterance, session: SessionPair) -> BoundUtterance:
    return BoundUtterance(utterance, session, uuid4(), datetime.now().astimezone())


class PipelineEventKind(StrEnum):
    """Turn-level failures the shell shows as notices (CAP-0168 spec §2.3.4)."""

    QUEUE_OVERFLOW = "queue_overflow"  # the oldest pending segment was dropped
    TURNS_DROPPED = "turns_dropped"  # queued segments not translated before Stop
    PLAYBACK_FAILED = "playback_failed"  # spoken output failed; the turn stays as text
    SYNTHESIS_FAILED = "synthesis_failed"  # one turn was not spoken; it stays as text
    TURN_FAILED = "turn_failed"  # one turn failed (``report_turn_failures``); CAP-0170 C §7


class FailureReason(StrEnum):
    """Why one turn or text job failed (moved unchanged from ``text_translation.jobs``)."""

    MODEL = "model"
    MEMORY = "memory"
    DEVICE = "device"  # playback only: the speakers could not be opened
    OTHER = "other"


def classify_failure(error: BaseException) -> FailureReason:
    names = {cls.__name__ for cls in type(error).__mro__}
    if isinstance(error, MemoryError) or "OutOfMemoryError" in names:
        return FailureReason.MEMORY
    if isinstance(error, RuntimeError) and "out of memory" in str(error).lower():
        return FailureReason.MEMORY  # torch CPU allocation failure
    if (
        isinstance(error, CapabilityMissingError | OSError | ImportError)
        or "ModelLoadError" in names
    ):
        return FailureReason.MODEL  # OSError covers FileNotFoundError and load I/O errors
    return FailureReason.OTHER


@dataclass(frozen=True, slots=True)
class PipelineEvent:
    """A notice event; ``message`` is technical detail for the local diagnostics log only."""

    kind: PipelineEventKind
    count: int = 1
    language: LanguageId | None = None
    message: str = ""
    turn_id: UUID | None = None  # QUEUE_OVERFLOW: the dropped item; TURN_FAILED: the turn
    turn_ids: tuple[UUID, ...] = ()  # TURNS_DROPPED: every dropped item
    failure: FailureReason | None = None  # TURN_FAILED only


@dataclass(frozen=True, slots=True)
class _RetainedTurn:
    held: HeldTurn
    item: BoundUtterance  # the retained audio and its bound session pair


DEFAULT_DETECTION_MIN_PROBABILITY = 0.7  # settings v2 ``languages.detection_min_probability``


def _warm_up(component: object, subjects: tuple[object, ...]) -> None:
    warm_up = getattr(component, "warm_up", None)
    if warm_up is not None:
        warm_up(subjects)


def _captured_at(held: HeldTurn) -> datetime:
    return held.captured_at
