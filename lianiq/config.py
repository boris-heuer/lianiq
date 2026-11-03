from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from lianiq.config_migration import (
    SCHEMA_VERSION,
    backup_legacy_settings,
    languages_from_legacy_mode,
    legacy_mode_from_languages,
    read_settings_file,
)

PROJECT_ROOT = (
    Path(sys.executable).resolve().parent
    if getattr(sys, "frozen", False)
    else Path(__file__).resolve().parent.parent
)
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "settings.json"
LOCAL_CONFIG_PATH = PROJECT_ROOT / "config" / "settings.local.json"

_ROUTINGS = frozenset({"bidirectional", "fixed"})
_OUTPUTS = frozenset({"text", "spoken"})


@dataclass(slots=True)
class LanguagesConfig:
    """Session language pair and usage-mode defaults (settings schema v2)."""

    pair: list[str] = field(default_factory=lambda: ["de", "zh-Hans"])
    routing: str = "bidirectional"
    fixed_source: str | None = None
    output: str = "text"
    detection_min_probability: float = 0.7

    def __post_init__(self) -> None:
        if len(self.pair) != 2 or self.pair[0] == self.pair[1]:
            raise ValueError("languages.pair must name two different language IDs")
        if self.routing not in _ROUTINGS:
            raise ValueError(f"Unsupported languages.routing: {self.routing!r}")
        if (self.routing == "fixed") != (self.fixed_source is not None):
            raise ValueError("languages.fixed_source is required exactly for fixed routing")
        if self.fixed_source is not None and self.fixed_source not in self.pair:
            raise ValueError("languages.fixed_source must be a member of languages.pair")
        if self.output not in _OUTPUTS:
            raise ValueError(f"Unsupported languages.output: {self.output!r}")
        if not 0.0 <= self.detection_min_probability <= 1.0:
            raise ValueError("languages.detection_min_probability must be between 0 and 1")


@dataclass(slots=True)
class AudioConfig:
    sample_rate: int = 16_000
    chunk_ms: int = 30
    start_rms: float = 0.018
    end_silence_ms: int = 600
    pre_roll_ms: int = 180
    min_speech_ms: int = 240
    max_speech_seconds: float = 12.0
    input_device: int | None = None
    output_device: int | None = None


@dataclass(slots=True)
class SpeechToTextConfig:
    model_path: str = "models/faster-whisper-small"
    languages: list[str] = field(default_factory=lambda: ["de", "zh-Hans"])
    device: str = "auto"
    compute_type: str = "int8"
    cpu_threads: int = 8
    beam_size: int = 1


@dataclass(slots=True)
class TranslationEdgeConfig:
    """One directed translation edge; its reverse edge is configured separately."""

    model_path: str


def _default_edges() -> dict[str, TranslationEdgeConfig]:
    return {
        "de>zh-Hans": TranslationEdgeConfig("models/opus-mt-de-zh"),
        "zh-Hans>de": TranslationEdgeConfig("models/opus-mt-zh-de"),
    }


@dataclass(slots=True)
class TranslationConfig:
    # Keyed "<source>><target>" by language ID (contract.md §4.2).
    edges: dict[str, TranslationEdgeConfig] = field(default_factory=_default_edges)
    cpu_threads: int = 8
    device: str = "auto"
    context_sentences: int = 5
    glossary_path: str = "config/glossary.json"

    def __post_init__(self) -> None:
        self.edges = {
            key: edge if isinstance(edge, TranslationEdgeConfig) else TranslationEdgeConfig(**edge)
            for key, edge in self.edges.items()
        }
        for key in self.edges:
            source, separator, target = key.partition(">")
            if not separator or not source or not target or ">" in target:
                raise ValueError(f"translation.edges key must be '<source>><target>': {key!r}")

    # Compatibility accessors for the de/zh translator until WI-03 moves it to edges.
    @property
    def de_zh_model_path(self) -> str:
        return self._edge_path("de>zh-Hans")

    @property
    def zh_de_model_path(self) -> str:
        return self._edge_path("zh-Hans>de")

    def _edge_path(self, key: str) -> str:
        edge = self.edges.get(key)
        return edge.model_path if edge is not None else ""


@dataclass(slots=True)
class TtsConfig:
    # A redistributable Mandarin voice is intentionally not bundled. Spoken output is
    # selected by ``languages.output`` and stays "text" until the operator provisions
    # and reviews both configured voices.
    voices: dict[str, str] = field(
        default_factory=lambda: {
            "de": "models/piper/de_DE-thorsten-medium.onnx",
            "zh-Hans": "models/piper/zh_CN-user-provided.onnx",
        }
    )
    length_scale: float = 1.0
    device: str = "auto"

    # Compatibility accessors for the de/zh voice adapter until WI-03 moves it to IDs.
    @property
    def de_voice_path(self) -> str:
        return self.voices.get("de", "")

    @property
    def zh_voice_path(self) -> str:
        return self.voices.get("zh-Hans", "")


@dataclass(slots=True)
class UiConfig:
    log_level: str = "INFO"


@dataclass(slots=True)
class CallBridgeConfig:
    local_language: str = "de"
    enabled: bool = False
    local_microphone_endpoint_id: str | None = None
    call_microphone_render_endpoint_id: str | None = None
    call_speaker_capture_endpoint_id: str | None = None
    local_headphones_endpoint_id: str | None = None
    failure_policy: str = "mute"
    max_pending_age_ms: int = 4_000

    def __post_init__(self) -> None:
        if self.failure_policy != "mute":
            raise ValueError("Only the fail-closed 'mute' call bridge policy is supported")
        if self.max_pending_age_ms <= 0:
            raise ValueError("call_bridge.max_pending_age_ms must be positive")
        if not self.local_language:
            raise ValueError("call_bridge.local_language must name a language ID")


@dataclass(slots=True)
class AppConfig:
    schema_version: int = SCHEMA_VERSION
    languages: LanguagesConfig = field(default_factory=LanguagesConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    speech_to_text: SpeechToTextConfig = field(default_factory=SpeechToTextConfig)
    translation: TranslationConfig = field(default_factory=TranslationConfig)
    tts: TtsConfig = field(default_factory=TtsConfig)
    ui: UiConfig = field(default_factory=UiConfig)
    call_bridge: CallBridgeConfig = field(default_factory=CallBridgeConfig)

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(f"Unsupported settings schema_version: {self.schema_version!r}")

    @classmethod
    def load(cls, path: Path | None = None) -> AppConfig:
        """Load settings; each file is migrated to schema v2 on its own, then merged.

        Raises ``SettingsMigrationError`` for a legacy value that cannot be mapped.
        Loading never writes a file.
        """
        if path is not None:
            return cls.from_mapping(read_settings_file(path))
        raw: dict[str, Any] = {}
        for config_path in (DEFAULT_CONFIG_PATH, LOCAL_CONFIG_PATH):
            raw = merge_dict(raw, read_settings_file(config_path))
        return cls.from_mapping(raw)

    @classmethod
    def from_mapping(cls, raw: dict[str, Any]) -> AppConfig:
        """Build the configuration from a (possibly partial) schema v2 mapping."""
        return cls(
            schema_version=raw.get("schema_version", SCHEMA_VERSION),
            languages=LanguagesConfig(**raw.get("languages", {})),
            audio=AudioConfig(**raw.get("audio", {})),
            speech_to_text=SpeechToTextConfig(**raw.get("speech_to_text", {})),
            translation=TranslationConfig(**raw.get("translation", {})),
            tts=TtsConfig(**raw.get("tts", {})),
            ui=UiConfig(**raw.get("ui", {})),
            call_bridge=CallBridgeConfig(**raw.get("call_bridge", {})),
        )

    def save(self, path: Path | None = None) -> None:
        # Runtime selections can contain user-specific Windows endpoint IDs. The
        # repository default is read-only; normal saves go to the ignored overlay.
        config_path = path or LOCAL_CONFIG_PATH
        if config_path.resolve() == DEFAULT_CONFIG_PATH.resolve():
            raise ValueError("Settings are never saved to the repository default file")
        config_path.parent.mkdir(parents=True, exist_ok=True)
        # A legacy (schema v1) file is kept once, byte for byte, before it is replaced.
        backup_legacy_settings(config_path)
        config_path.write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    # Compatibility accessors for the de/zh conversation UI until WI-04 moves it to
    # language IDs and usage modes.
    @property
    def voice_output(self) -> bool:
        return self.languages.output == "spoken"

    @voice_output.setter
    def voice_output(self, enabled: bool) -> None:
        self.languages.output = "spoken" if enabled else "text"

    @property
    def legacy_mode(self) -> str:
        return legacy_mode_from_languages(self.languages.routing, self.languages.fixed_source)

    @legacy_mode.setter
    def legacy_mode(self, mode: str) -> None:
        self.languages.routing, self.languages.fixed_source = languages_from_legacy_mode(mode)

    @staticmethod
    def resolve(value: str) -> Path:
        path = Path(value).expanduser()
        return path if path.is_absolute() else PROJECT_ROOT / path


def merge_dict(target: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge configuration mappings without mutating inputs."""
    result = dict(target)
    for key, value in source.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge_dict(result[key], value)
        else:
            result[key] = value
    return result
