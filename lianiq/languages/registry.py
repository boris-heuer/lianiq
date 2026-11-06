"""Language identifiers, the language registry and language pairs (contract.md §3.1.1)."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import NewType

from lianiq.languages.errors import (
    PlannedLanguageError,
    SameLanguagePairError,
    UnknownLanguageError,
)

LanguageId = NewType("LanguageId", str)
"""A BCP 47 language tag in canonical case, e.g. ``de`` or ``zh-Hans``."""


def normalize_language_id(tag: str) -> LanguageId:
    """Return ``tag`` in BCP 47 canonical case (language lower, Script title, REGION upper)."""
    subtags = tag.strip().replace("_", "-").split("-")
    if not subtags or not subtags[0]:
        raise UnknownLanguageError(tag)
    normalized = [subtags[0].lower()]
    for subtag in subtags[1:]:
        if len(subtag) == 4 and subtag.isalpha():
            normalized.append(subtag.title())
        elif (len(subtag) == 2 and subtag.isalpha()) or (len(subtag) == 3 and subtag.isdigit()):
            normalized.append(subtag.upper())
        else:
            normalized.append(subtag.lower())
    return LanguageId("-".join(normalized))


class Availability(str, Enum):
    QUALIFIED = "qualified"
    PLANNED = "planned"


@dataclass(frozen=True, slots=True)
class LanguageDefinition:
    id: LanguageId
    english_name: str
    native_name: str
    engine_codes: Mapping[str, str]
    availability: Availability

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", normalize_language_id(self.id))
        object.__setattr__(self, "engine_codes", MappingProxyType(dict(self.engine_codes)))


@dataclass(frozen=True, slots=True)
class LanguagePair:
    """An unordered pair selection; members are stored in registry order."""

    first: LanguageId
    second: LanguageId

    def __post_init__(self) -> None:
        if self.first == self.second:
            raise SameLanguagePairError(self.first)

    @property
    def members(self) -> tuple[LanguageId, LanguageId]:
        return (self.first, self.second)

    def __contains__(self, language_id: object) -> bool:
        return language_id in (self.first, self.second)

    def other(self, language_id: LanguageId) -> LanguageId:
        """Return the other pair member; ``language_id`` must be a member."""
        if language_id == self.first:
            return self.second
        if language_id == self.second:
            return self.first
        raise ValueError(f"{language_id!r} is not a member of the pair {self.first}/{self.second}")


class LanguageRegistry:
    def __init__(self, definitions: Iterable[LanguageDefinition]) -> None:
        self._definitions = tuple(definitions)
        self._by_id: dict[LanguageId, LanguageDefinition] = {}
        for definition in self._definitions:
            if definition.id in self._by_id:
                raise ValueError(f"Duplicate language ID in registry: {definition.id!r}")
            self._by_id[definition.id] = definition
        self._order = {definition.id: index for index, definition in enumerate(self._definitions)}

    def get(self, language_id: str) -> LanguageDefinition:
        try:
            normalized = normalize_language_id(language_id)
        except UnknownLanguageError:
            raise UnknownLanguageError(language_id) from None
        try:
            return self._by_id[normalized]
        except KeyError:
            raise UnknownLanguageError(language_id) from None

    def languages(self) -> tuple[LanguageDefinition, ...]:
        return self._definitions

    def display_name(self, language_id: str) -> str:
        return self.get(language_id).english_name

    def from_engine_code(self, engine: str, code: str) -> LanguageId | None:
        for definition in self._definitions:
            if definition.engine_codes.get(engine) == code:
                return definition.id
        return None

    def pair(self, a: str, b: str) -> LanguagePair:
        first = self.get(a)
        second = self.get(b)
        if first.id == second.id:
            raise SameLanguagePairError(first.id)
        for member in (first, second):
            if member.availability is not Availability.QUALIFIED:
                raise PlannedLanguageError(member.id)
        if self._order[first.id] > self._order[second.id]:
            first, second = second, first
        return LanguagePair(first.id, second.id)


BUILTIN_LANGUAGES: tuple[LanguageDefinition, ...] = (
    LanguageDefinition(
        LanguageId("de"),
        "German",
        "Deutsch",
        {"whisper": "de", "piper": "de_DE"},
        Availability.QUALIFIED,
    ),
    LanguageDefinition(
        LanguageId("zh-Hans"),
        "Mandarin (Simplified)",
        "普通话（简体）",
        {"whisper": "zh", "piper": "zh_CN", "sherpa-onnx": "zh"},
        Availability.QUALIFIED,
    ),
    LanguageDefinition(
        LanguageId("en"),
        "English",
        "English",
        {"whisper": "en", "piper": "en_US"},
        Availability.PLANNED,
    ),
    LanguageDefinition(
        LanguageId("es"),
        "Spanish",
        "Español",
        {"whisper": "es", "piper": "es_ES"},
        Availability.PLANNED,
    ),
    LanguageDefinition(
        LanguageId("fr"),
        "French",
        "Français",
        {"whisper": "fr", "piper": "fr_FR"},
        Availability.PLANNED,
    ),
)

BUILTIN_REGISTRY = LanguageRegistry(BUILTIN_LANGUAGES)
