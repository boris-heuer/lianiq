from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Protocol

from lianiq.languages.errors import CapabilityMissingError
from lianiq.languages.registry import BUILTIN_REGISTRY, LanguageId, LanguageRegistry
from lianiq.languages.requirements import Requirement, RequirementKind


class VoiceEngine(Protocol):
    """``device`` and ``validate_voice_files`` are optional, as for any synthesizer."""

    def synthesize(self, text: str, language: str) -> Path: ...

    def warm_up(self, languages: Iterable[str]) -> None: ...


class VoiceRouter:
    """One synthesizer over per-language engines (for example Piper and sherpa-onnx).

    Each configured language is served by exactly one engine; a language without an
    engine raises ``CapabilityMissingError``.
    """

    def __init__(
        self,
        engines: Mapping[str, VoiceEngine],
        registry: LanguageRegistry = BUILTIN_REGISTRY,
    ) -> None:
        self.registry = registry
        self.engines: dict[LanguageId, VoiceEngine] = {
            registry.get(language).id: engine for language, engine in engines.items()
        }

    @property
    def device(self) -> str:
        devices = sorted(
            {str(getattr(engine, "device", "unknown")) for engine in self.engines.values()}
        )
        return ",".join(devices) if devices else "none"

    def _engine(self, language: str) -> tuple[LanguageId, VoiceEngine]:
        language_id = self.registry.get(language).id
        engine = self.engines.get(language_id)
        if engine is None:
            raise CapabilityMissingError(Requirement(RequirementKind.VOICE, language_id))
        return language_id, engine

    def validate_voice_files(self, languages: Iterable[str] | None = None) -> None:
        for language in self.engines if languages is None else languages:
            language_id, engine = self._engine(language)
            validate = getattr(engine, "validate_voice_files", None)
            if validate is not None:
                validate((language_id,))

    def warm_up(self, languages: Iterable[str]) -> None:
        for language in languages:
            language_id, engine = self._engine(language)
            engine.warm_up((language_id,))

    def synthesize(self, text: str, language: str) -> Path:
        language_id, engine = self._engine(language)
        return engine.synthesize(text, language_id)
