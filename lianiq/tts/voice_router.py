from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Protocol

import numpy as np

from lianiq.languages.errors import CapabilityMissingError
from lianiq.languages.registry import BUILTIN_REGISTRY, LanguageId, LanguageRegistry
from lianiq.languages.requirements import Requirement, RequirementKind
from lianiq.tts.voice_controls import VoiceControls, VoiceOptions

# An engine without ``controls`` offers no Voice, Rate or Volume control.
NO_CONTROLS = VoiceControls(speakers=1, rate=False, volume=False)


class VoiceEngine(Protocol):
    """``device``, ``validate_voice_files``, ``controls`` and ``load_controls`` are optional."""

    def synthesize(self, text: str, language: str, options: VoiceOptions | None = None) -> Path: ...

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

    def synthesize_pcm(self, text: str, language: str) -> tuple[np.ndarray, int]:
        """In-memory synthesis (``PcmSynthesizer``): PCM16 mono samples and sample rate."""
        language_id, engine = self._engine(language)
        return engine.synthesize_pcm(text, language_id)

    def controls(self, language: str) -> VoiceControls:
        """The controls of ``language``'s engine; never loads a voice (contract §3)."""
        language_id, engine = self._engine(language)
        controls = getattr(engine, "controls", None)
        return NO_CONTROLS if controls is None else controls(language_id)

    def load_controls(self, language: str) -> VoiceControls:
        """Like ``controls``, but loads the cached voice if needed; worker thread only."""
        language_id, engine = self._engine(language)
        load = getattr(engine, "load_controls", None)
        return self.controls(language_id) if load is None else load(language_id)

    def bound(self, options: Mapping[str, VoiceOptions]) -> BoundVoice:
        """A synthesizer over the cached engines that applies ``options`` per language."""
        return BoundVoice(self, options)


class BoundVoice:
    """The CAP-0169 ``Synthesizer`` protocol with fixed per-language voice options.

    A language missing from ``options`` uses ``VoiceOptions()``.
    """

    def __init__(self, router: VoiceRouter, options: Mapping[str, VoiceOptions]) -> None:
        self._router = router
        self._options: dict[LanguageId, VoiceOptions] = {
            router.registry.get(language).id: value for language, value in options.items()
        }

    def _bind(self, language: str) -> tuple[LanguageId, VoiceEngine, VoiceOptions]:
        language_id, engine = self._router._engine(language)
        return language_id, engine, self._options.get(language_id, VoiceOptions())

    @property
    def device(self) -> str:
        return self._router.device

    def validate_voice_files(self, languages: Iterable[str] | None = None) -> None:
        self._router.validate_voice_files(languages)

    def warm_up(self, languages: Iterable[str]) -> None:
        self._router.warm_up(languages)

    def synthesize(self, text: str, language: str) -> Path:
        language_id, engine, options = self._bind(language)
        return engine.synthesize(text, language_id, options)

    def synthesize_pcm(self, text: str, language: str) -> tuple[np.ndarray, int]:
        language_id, engine, options = self._bind(language)
        return engine.synthesize_pcm(text, language_id, options)


def bind_options(synthesizer: object, options: Mapping[str, VoiceOptions]) -> object:
    """``synthesizer.bound(options)``; a synthesizer without ``bound`` is used as it is."""
    bound = getattr(synthesizer, "bound", None)
    return synthesizer if bound is None else bound(options)
