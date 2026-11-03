"""Errors of the language pair contract (contract.md §3.1.8)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lianiq.languages.requirements import Requirement


class LanguageContractError(Exception):
    """Base class for every language pair contract error."""


class UnknownLanguageError(LanguageContractError, LookupError):
    """A language ID is not in the registry."""

    def __init__(self, language_id: str) -> None:
        super().__init__(f"Unknown language ID: {language_id!r}")
        self.language_id = language_id


class PlannedLanguageError(LanguageContractError, ValueError):
    """A planned (not yet qualified) language was used in a pair."""

    def __init__(self, language_id: str) -> None:
        super().__init__(f"Language {language_id!r} is planned and cannot be used in a pair")
        self.language_id = language_id


class SameLanguagePairError(LanguageContractError, ValueError):
    """Both members of a pair (or both ends of an edge) are the same language."""

    def __init__(self, language_id: str) -> None:
        super().__init__(
            f"A language pair needs two different languages, got {language_id!r} twice"
        )
        self.language_id = language_id


class UnsupportedModeError(LanguageContractError, ValueError):
    """The usage mode is invalid, e.g. typed + bidirectional or FIXED without a source."""


class ModeUnavailableError(LanguageContractError):
    """A session was started while required capabilities or devices are missing."""

    def __init__(self, missing: tuple[Requirement, ...]) -> None:
        super().__init__(f"Usage mode unavailable; missing: {', '.join(map(str, missing))}")
        self.missing = missing


class CapabilityMissingError(LanguageContractError):
    """An adapter was asked for an unconfigured edge, voice or recognition language."""

    def __init__(self, requirement: Requirement) -> None:
        super().__init__(f"Capability not configured: {requirement}")
        self.requirement = requirement


class PairLockedError(LanguageContractError, RuntimeError):
    """The session pair or mode was changed while a session runs."""


class SettingsMigrationError(LanguageContractError, ValueError):
    """A legacy settings value cannot be mapped; the settings file is left untouched."""

    def __init__(self, key: str) -> None:
        super().__init__(f"Cannot migrate legacy setting {key!r}")
        self.key = key
