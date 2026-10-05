from __future__ import annotations

import json
from pathlib import Path

from offline_translator.config import AppConfig


def test_config_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    config = AppConfig()
    config.audio.start_rms = 0.025
    config.translation.context_sentences = 7
    config.save(path)

    loaded = AppConfig.load(path)
    assert loaded.audio.start_rms == 0.025
    assert loaded.translation.context_sentences == 7
    assert json.loads(path.read_text(encoding="utf-8"))["tts"]["enabled"] is True


def test_missing_config_uses_hardware_defaults(tmp_path: Path) -> None:
    config = AppConfig.load(tmp_path / "missing.json")
    assert config.speech_to_text.device == "auto"
    assert config.translation.device == "auto"
    assert config.tts.device == "auto"
    assert config.speech_to_text.compute_type == "int8"
    assert config.speech_to_text.cpu_threads == 8


def test_legacy_tts_cuda_setting_is_migrated(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text('{"tts": {"use_cuda": true}}', encoding="utf-8")

    config = AppConfig.load(path)

    assert config.tts.device == "cuda"
