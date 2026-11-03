"""Turn data shared by the conversation pipeline, the Call Bridge and the UI.

Languages are registry ``LanguageId`` values (CAP-0169 contract.md §3.1.5 and §3.1.7);
there is no language enum and no conversation-mode enum.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import numpy as np

from lianiq.languages.registry import LanguageId


@dataclass(frozen=True, slots=True)
class AudioUtterance:
    samples: np.ndarray
    sample_rate: int


@dataclass(frozen=True, slots=True)
class Transcript:
    text: str
    language: LanguageId | None  # None if the detected language is not in the registry
    probability: float
    duration_seconds: float
    engine_language_code: str = ""  # raw recogniser code, e.g. Whisper "zh"


@dataclass(frozen=True, slots=True)
class TranslationResult:
    """One completed turn; its languages never change after it was produced."""

    turn_id: UUID
    captured_at: datetime
    source_text: str
    translated_text: str
    source_language: LanguageId
    target_language: LanguageId
    stt_seconds: float
    translation_seconds: float
    tts_seconds: float = 0.0

    @property
    def total_seconds(self) -> float:
        return self.stt_seconds + self.translation_seconds + self.tts_seconds
