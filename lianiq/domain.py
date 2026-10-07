from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np


class Language(str, Enum):
    GERMAN = "de"
    MANDARIN = "zh"

    @property
    def other(self) -> Language:
        return Language.MANDARIN if self is Language.GERMAN else Language.GERMAN


class ConversationMode(str, Enum):
    AUTO = "auto"
    DE_TO_ZH = "de-zh"
    ZH_TO_DE = "zh-de"

    @property
    def forced_source(self) -> Language | None:
        if self is ConversationMode.DE_TO_ZH:
            return Language.GERMAN
        if self is ConversationMode.ZH_TO_DE:
            return Language.MANDARIN
        return None


@dataclass(frozen=True, slots=True)
class AudioUtterance:
    samples: np.ndarray
    sample_rate: int


@dataclass(frozen=True, slots=True)
class Transcript:
    text: str
    language: Language
    probability: float
    duration_seconds: float


@dataclass(frozen=True, slots=True)
class TranslationResult:
    source_text: str
    translated_text: str
    source_language: Language
    target_language: Language
    stt_seconds: float
    translation_seconds: float
    tts_seconds: float = 0.0

    @property
    def total_seconds(self) -> float:
        return self.stt_seconds + self.translation_seconds + self.tts_seconds
