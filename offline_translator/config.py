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
    enabled: bool = True
    de_voice_path: str = "models/piper/de_DE-thorsten-medium.onnx"
    zh_voice_path: str = "models/piper/zh_CN-huayan-medium.onnx"
    length_scale: float = 1.0
    device: str = "auto"


@dataclass(slots=True)
class UiConfig:
    mode: str = "auto"
    log_level: str = "INFO"


@dataclass(slots=True)
class AppConfig:
    audio: AudioConfig = field(default_factory=AudioConfig)
    speech_to_text: SpeechToTextConfig = field(default_factory=SpeechToTextConfig)
    translation: TranslationConfig = field(default_factory=TranslationConfig)
    tts: TtsConfig = field(default_factory=TtsConfig)
    ui: UiConfig = field(default_factory=UiConfig)

    @classmethod
    def load(cls, path: Path | None = None) -> AppConfig:
        config_path = path or PROJECT_ROOT / "config" / "settings.json"
        if not config_path.exists():
            return cls()
        raw = json.loads(config_path.read_text(encoding="utf-8"))
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
        )

    def save(self, path: Path | None = None) -> None:
        config_path = path or PROJECT_ROOT / "config" / "settings.json"
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
