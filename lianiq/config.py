from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from lianiq.config_listen import ListenConfig
from lianiq.config_meeting import validate_meeting_config
from lianiq.config_migration import (
    SCHEMA_VERSION,
    backup_legacy_settings,
    read_settings_file,
)
from lianiq.config_provisioning import ProvisioningConfig, provisioning_from_mapping
from lianiq.config_translation import TranslationEdgeConfig, edges_from_mapping, union_languages
from lianiq.config_voice import VoiceEngineConfig, VoiceOutputPreference, output_preferences

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
    # Legacy PortAudio indices: read once for migration, saved as ``null`` (CAP-0168 §7).
    input_device: int | None = None
    output_device: int | None = None
    # Device choice by identity: policy ``null`` = not yet migrated (CAP-0168 contract §7).
    input_policy: str | None = None
    output_policy: str | None = None
    input_endpoint_id: str | None = None
    output_endpoint_id: str | None = None
    input_device_name: str | None = None
    output_device_name: str | None = None

    def __post_init__(self) -> None:
        for policy in (self.input_policy, self.output_policy):
            if policy not in (None, "explicit", "follow_default"):
                raise ValueError(f"Unsupported audio device policy: {policy!r}")


@dataclass(slots=True)
class SpeechToTextConfig:
    model_path: str = "models/faster-whisper-small"
    languages: list[str] = field(default_factory=lambda: ["de", "zh-Hans", "en"])
    device: str = "auto"
    compute_type: str = "int8"
    cpu_threads: int = 8
    beam_size: int = 1


def _default_edges() -> dict[str, TranslationEdgeConfig]:
    return {
        "de>zh-Hans": TranslationEdgeConfig("models/opus-mt-de-zh"),
        "zh-Hans>de": TranslationEdgeConfig("models/opus-mt-zh-de"),
        "en>zh-Hans": TranslationEdgeConfig("models/opus-mt-en-zh", ">>cmn_Hans<<"),
        "zh-Hans>en": TranslationEdgeConfig("models/opus-mt-zh-en"),
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
        self.edges = edges_from_mapping(self.edges)


@dataclass(slots=True)
class TtsConfig:
    # A Piper voice is an ``.onnx`` file with its ``.onnx.json`` metadata; a sherpa-onnx
    # voice is a model directory. Spoken output is selected by ``languages.output`` and
    # stays "text" until the operator provisions both configured voices.
    voices: dict[str, str] = field(
        default_factory=lambda: {
            "de": "models/piper/de_DE-thorsten-medium.onnx",
            "zh-Hans": "models/sherpa/vits-icefall-zh-aishell3",
            "en": "models/piper-en_US-ljspeech-high/en_US-ljspeech-high.onnx",
        }
    )
    # Per-language engine selection (CAP-0169 WI-09); languages without an entry use Piper.
    engines: dict[str, VoiceEngineConfig] = field(
        default_factory=lambda: {
            "de": VoiceEngineConfig("piper"),
            "zh-Hans": VoiceEngineConfig(
                "sherpa-onnx", speaker_id=20, length_scale=1.15, system_voice="zh-CN"
            ),
            "en": VoiceEngineConfig("piper"),
        }
    )
    length_scale: float = 1.0
    device: str = "auto"
    output: dict[str, VoiceOutputPreference] = field(default_factory=dict)  # CAP-0167

    def __post_init__(self) -> None:
        self.output = output_preferences(self.output)
        self.engines = {
            key: value if isinstance(value, VoiceEngineConfig) else VoiceEngineConfig(**value)
            for key, value in self.engines.items()
        }


@dataclass(slots=True)
class UiConfig:
    log_level: str = "INFO"


@dataclass(slots=True)
class CallBridgeConfig:
    local_language: str = "de"
    enabled: bool = False  # still read from old files; never a Start gate (CAP-0166 §3.3)
    local_microphone_endpoint_id: str | None = None
    call_microphone_render_endpoint_id: str | None = None
    call_speaker_capture_endpoint_id: str | None = None
    local_headphones_endpoint_id: str | None = None
    failure_policy: str = "mute"
    max_pending_age_ms: int = 4_000
    guard_tail_ms: int = 300  # echo guard tail after inbound playback (CAP-0166 §3.3)

    def __post_init__(self) -> None:
        if type(self.guard_tail_ms) is not int or self.guard_tail_ms < 0:
            raise ValueError(f"call_bridge.guard_tail_ms must be >= 0: {self.guard_tail_ms!r}")
        if self.failure_policy != "mute":
            raise ValueError("Only the fail-closed 'mute' call bridge policy is supported")
        if self.max_pending_age_ms <= 0:
            raise ValueError("call_bridge.max_pending_age_ms must be positive")
        if not self.local_language:
            raise ValueError("call_bridge.local_language must name a language ID")


@dataclass(slots=True)
class MeetingConfig:
    """Meeting workspace settings (CAP-0177 contract.md §8), optional in schema v2.

    Endpoints are stored by identity only. ``local_language`` must also be a member of the
    session pair; ``SessionPair`` checks that when a meeting starts.
    """

    local_language: str = "de"
    table_capture_endpoint_id: str | None = None
    table_render_endpoint_id: str | None = None
    user_input_policy: str = "follow_default"
    user_input_endpoint_id: str | None = None  # used iff ``user_input_policy`` is explicit
    local_output_endpoint_id: str | None = None
    local_output_is_headset: bool = False  # fail-safe: unknown counts as a speaker
    speak_local: bool = False
    table_input_during_output: str = "mute"
    guard_tail_ms: int = 300
    max_playback_defer_ms: int = 5_000

    def __post_init__(self) -> None:
        validate_meeting_config(self)


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
    meeting: MeetingConfig = field(default_factory=MeetingConfig)
    provisioning: ProvisioningConfig = field(default_factory=ProvisioningConfig)  # CAP-0171
    listen: ListenConfig = field(default_factory=ListenConfig)  # CAP-0170

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
        """Build the configuration from a (possibly partial) schema v2 mapping.

        Saved recognition languages gain the missing defaults (CAP-0181 spec §3.2).
        """
        stt = dict(raw.get("speech_to_text", {}))
        if "languages" in stt:
            stt["languages"] = union_languages(stt["languages"], SpeechToTextConfig().languages)
        return cls(
            schema_version=raw.get("schema_version", SCHEMA_VERSION),
            languages=LanguagesConfig(**raw.get("languages", {})),
            audio=AudioConfig(**raw.get("audio", {})),
            speech_to_text=SpeechToTextConfig(**stt),
            translation=TranslationConfig(**raw.get("translation", {})),
            tts=TtsConfig(**raw.get("tts", {})),
            ui=UiConfig(**raw.get("ui", {})),
            call_bridge=CallBridgeConfig(**raw.get("call_bridge", {})),
            meeting=MeetingConfig(**raw.get("meeting", {})),
            provisioning=provisioning_from_mapping(raw.get("provisioning", {})),
            listen=ListenConfig(**raw.get("listen", {})),
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

    # ``languages.output`` as a flag: spoken output on or off.
    @property
    def voice_output(self) -> bool:
        return self.languages.output == "spoken"

    @voice_output.setter
    def voice_output(self, enabled: bool) -> None:
        self.languages.output = "spoken" if enabled else "text"

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
