from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np

from lianiq.languages.registry import LanguageId


class Language(str, Enum):
    GERMAN = "de"
    MANDARIN = "zh"

    @property
    def other(self) -> Language:
        return Language.MANDARIN if self is Language.GERMAN else Language.GERMAN

    # Transitional bridge to registry language IDs while routing, results and the UI
    # still use this enum (removed with it by CAP-0169 WI-04). Adapters take IDs only.
    @property
    def id(self) -> LanguageId:
        return _LANGUAGE_IDS[self]

    @classmethod
    def from_id(cls, language_id: str | None) -> Language | None:
        """The enum member for a registry ID, or ``None`` for any other ID (no guessing)."""
        for member, member_id in _LANGUAGE_IDS.items():
            if language_id == member_id:
                return member
        return None


_LANGUAGE_IDS: dict[Language, LanguageId] = {
    Language.GERMAN: LanguageId("de"),
    Language.MANDARIN: LanguageId("zh-Hans"),
}


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
    language: LanguageId | None  # None if the detected language is not in the registry
    probability: float
    duration_seconds: float
    engine_language_code: str = ""  # raw recogniser code, e.g. Whisper "zh"


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
