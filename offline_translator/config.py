from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

PROJECT_ROOT = (
    Path(sys.executable).resolve().parent
    if getattr(sys, "frozen", False)
    else Path(__file__).resolve().parent.parent
)
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "settings.json"
LOCAL_CONFIG_PATH = PROJECT_ROOT / "config" / "settings.local.json"


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
    device: str = "auto"
    compute_type: str = "int8"
    cpu_threads: int = 8
    beam_size: int = 1


@dataclass(slots=True)
class TranslationConfig:
    de_zh_model_path: str = "models/opus-mt-de-zh"
    zh_de_model_path: str = "models/opus-mt-zh-de"
    cpu_threads: int = 8
    device: str = "auto"
    context_sentences: int = 5
    glossary_path: str = "config/glossary.json"


@dataclass(slots=True)
class TtsConfig:
    # A redistributable Mandarin voice is intentionally not bundled. Keep spoken
    # output off until the operator provisions and reviews both configured voices.
    enabled: bool = False
    de_voice_path: str = "models/piper/de_DE-thorsten-medium.onnx"
    zh_voice_path: str = "models/piper/zh_CN-user-provided.onnx"
    length_scale: float = 1.0
    device: str = "auto"


@dataclass(slots=True)
class UiConfig:
    mode: str = "auto"
    log_level: str = "INFO"


@dataclass(slots=True)
class CallBridgeConfig:
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


@dataclass(slots=True)
class AppConfig:
    audio: AudioConfig = field(default_factory=AudioConfig)
    speech_to_text: SpeechToTextConfig = field(default_factory=SpeechToTextConfig)
    translation: TranslationConfig = field(default_factory=TranslationConfig)
    tts: TtsConfig = field(default_factory=TtsConfig)
    ui: UiConfig = field(default_factory=UiConfig)
    call_bridge: CallBridgeConfig = field(default_factory=CallBridgeConfig)

    @classmethod
    def load(cls, path: Path | None = None) -> AppConfig:
        if path is not None:
            raw = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        else:
            raw: dict[str, Any] = {}
            for config_path in (DEFAULT_CONFIG_PATH, LOCAL_CONFIG_PATH):
                if config_path.exists():
                    raw = merge_dict(raw, json.loads(config_path.read_text(encoding="utf-8")))
        tts_raw = dict(raw.get("tts", {}))
        legacy_use_cuda = tts_raw.pop("use_cuda", None)
        if legacy_use_cuda is not None and "device" not in tts_raw:
            tts_raw["device"] = "cuda" if legacy_use_cuda else "cpu"
        return cls(
            audio=AudioConfig(**raw.get("audio", {})),
            speech_to_text=SpeechToTextConfig(**raw.get("speech_to_text", {})),
            translation=TranslationConfig(**raw.get("translation", {})),
            tts=TtsConfig(**tts_raw),
            ui=UiConfig(**raw.get("ui", {})),
            call_bridge=CallBridgeConfig(**raw.get("call_bridge", {})),
        )

    def save(self, path: Path | None = None) -> None:
        # Runtime selections can contain user-specific Windows endpoint IDs. The
        # repository default is read-only; normal saves go to the ignored overlay.
        config_path = path or LOCAL_CONFIG_PATH
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

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
