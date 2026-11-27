"""Per-language voice output settings ``tts.output`` (CAP-0167 contract.md §6, spec §4.1).

Qt-free. ``TtsConfig.output`` in ``config.py`` holds a ``VoiceOutputPreference`` per language
ID; this module defines it, checks a settings file's ``tts.output`` block and offers
``VoicePreferences``, the accessor the UI and the spoken output use. A file without
``tts.output`` leaves every preference at its default; a legacy ``languages.output`` is never
read into it (PO decision 2026-11-19).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, fields, replace
from typing import TYPE_CHECKING, Any

from lianiq.languages.errors import LanguageContractError, SettingsMigrationError
from lianiq.languages.registry import BUILTIN_REGISTRY, LanguageId, LanguageRegistry
from lianiq.tts.voice_controls import VoiceOptions

if TYPE_CHECKING:
    from lianiq.config import AppConfig


VOICE_ENGINES = frozenset({"piper", "sherpa-onnx"})


@dataclass(slots=True)
class VoiceEngineConfig:
    """Engine of one language's voice; a language without an entry uses Piper.

    ``speaker_id``, ``length_scale`` and ``num_threads`` apply to sherpa-onnx voices only;
    Piper voices use ``tts.length_scale``. ``system_voice`` is a Windows voice language tag
    (for example ``zh-CN``) spoken in place of this voice when installed; empty: never.
    """

    engine: str = "piper"
    speaker_id: int = 0
    length_scale: float = 1.0
    num_threads: int = 4
    system_voice: str = ""

    def __post_init__(self) -> None:
        if self.engine not in VOICE_ENGINES:
            raise ValueError(f"Unsupported tts engine: {self.engine!r}")
        if self.speaker_id < 0:
            raise ValueError("tts speaker_id must not be negative")
        if self.length_scale <= 0:
            raise ValueError("tts length_scale must be positive")
        if self.num_threads <= 0:
            raise ValueError("tts num_threads must be positive")
        if not isinstance(self.system_voice, str):
            raise ValueError("tts system_voice must be a language tag or empty")  # noqa: TRY004


@dataclass(slots=True)
class VoiceOutputPreference:
    """One language's switch and voice options; values an engine lacks are kept but ignored."""

    enabled: bool | None = None  # None: on when the voice is ready
    speaker: int | None = None  # None: the engine's configured speaker
    rate: float = 1.0
    volume: float = 1.0

    def __post_init__(self) -> None:
        if self.enabled is not None and not isinstance(self.enabled, bool):
            raise ValueError(f"tts.output enabled must be true, false or null: {self.enabled!r}")
        self.options()  # range check of speaker, rate and volume

    def options(self) -> VoiceOptions:
        return VoiceOptions(self.speaker, self.rate, self.volume)


_FIELDS = frozenset(field.name for field in fields(VoiceOutputPreference))


def output_preferences(values: Mapping[str, Any]) -> dict[str, VoiceOutputPreference]:
    """``TtsConfig.output`` from its settings form; mapping values are converted."""
    return {
        key: value if isinstance(value, VoiceOutputPreference) else VoiceOutputPreference(**value)
        for key, value in values.items()
    }


def validate_output_settings(
    settings: Mapping[str, Any], registry: LanguageRegistry = BUILTIN_REGISTRY
) -> None:
    """Reject a ``tts.output`` block of one settings file, naming the first bad key.

    Keys must be registry language IDs in canonical case; each entry may only hold the
    ``VoiceOutputPreference`` fields, each in its range. Raises ``SettingsMigrationError``.
    """
    tts = settings.get("tts")
    if not isinstance(tts, Mapping) or "output" not in tts:
        return
    output = tts["output"]
    if not isinstance(output, Mapping):
        raise SettingsMigrationError("tts.output")
    for language, entry in output.items():
        key = f"tts.output.{language}"
        try:
            known = registry.get(str(language)).id == language
        except LanguageContractError:
            known = False
        if not known or not isinstance(entry, Mapping):
            raise SettingsMigrationError(key)
        for name, value in entry.items():
            if name not in _FIELDS:
                raise SettingsMigrationError(f"{key}.{name}")
            try:
                VoiceOutputPreference(**{name: value})
            except ValueError:
                raise SettingsMigrationError(f"{key}.{name}") from None


class VoicePreferences:
    """Reads and changes ``tts.output`` of ``config`` by language ID; the caller saves."""

    def __init__(self, config: AppConfig, registry: LanguageRegistry) -> None:
        self.config = config
        self.registry = registry

    def _id(self, language: str) -> LanguageId:
        return self.registry.get(language).id

    def get(self, language: LanguageId) -> VoiceOutputPreference:
        stored = self.config.tts.output.get(self._id(language))
        return VoiceOutputPreference() if stored is None else stored

    def set_enabled(self, language: LanguageId, enabled: bool) -> None:
        if not isinstance(enabled, bool):
            raise TypeError(f"A voice switch is on or off: {enabled!r}")
        self.config.tts.output[self._id(language)] = replace(self.get(language), enabled=enabled)

    def set_options(self, language: LanguageId, options: VoiceOptions) -> None:
        self.config.tts.output[self._id(language)] = replace(
            self.get(language), speaker=options.speaker, rate=options.rate, volume=options.volume
        )

    def options(self, language: LanguageId) -> VoiceOptions:
        return self.get(language).options()

    def snapshot(self, languages: Iterable[str]) -> dict[LanguageId, VoiceOptions]:
        """The options of ``languages`` now; Call Bridge and Meeting bind them at Start."""
        return {self._id(language): self.options(self._id(language)) for language in languages}

    def sync_output(self, plan: frozenset[LanguageId]) -> None:
        """``languages.output`` is ``spoken`` iff the spoken plan is non-empty, else ``text``."""
        self.config.languages.output = "spoken" if plan else "text"
