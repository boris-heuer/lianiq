from __future__ import annotations

import json
from pathlib import Path

import offline_translator.config as config_module
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
    assert json.loads(path.read_text(encoding="utf-8"))["tts"]["enabled"] is False


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


def test_default_config_is_overlaid_and_runtime_save_uses_ignored_local_file(
    tmp_path: Path, monkeypatch
) -> None:
    default_path = tmp_path / "settings.json"
    local_path = tmp_path / "settings.local.json"
    default_path.write_text(
        '{"audio": {"start_rms": 0.02}, "call_bridge": {"enabled": false}}',
        encoding="utf-8",
    )
    local_path.write_text(
        '{"call_bridge": {"enabled": true, "local_microphone_endpoint_id": "private-id"}}',
        encoding="utf-8",
    )
    monkeypatch.setattr(config_module, "DEFAULT_CONFIG_PATH", default_path)
    monkeypatch.setattr(config_module, "LOCAL_CONFIG_PATH", local_path)

    config = AppConfig.load()

    assert config.audio.start_rms == 0.02
    assert config.call_bridge.enabled is True
    assert config.call_bridge.local_microphone_endpoint_id == "private-id"

    config.call_bridge.local_microphone_endpoint_id = "updated-private-id"
    config.save()

    assert "updated-private-id" in local_path.read_text(encoding="utf-8")
    assert "private-id" not in default_path.read_text(encoding="utf-8")


def test_call_bridge_configuration_is_disabled_and_round_trips_stable_ids(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    config = AppConfig()
    assert config.call_bridge.enabled is False
    config.call_bridge.local_microphone_endpoint_id = "wasapi:capture:abc"
    config.call_bridge.call_microphone_render_endpoint_id = "wasapi:render:def"
    config.call_bridge.call_speaker_capture_endpoint_id = "wasapi:capture:ghi"
    config.call_bridge.local_headphones_endpoint_id = "wasapi:render:jkl"
    config.save(path)

    loaded = AppConfig.load(path)

    assert loaded.call_bridge.local_microphone_endpoint_id == "wasapi:capture:abc"
    assert loaded.call_bridge.call_microphone_render_endpoint_id == "wasapi:render:def"
    assert loaded.call_bridge.call_speaker_capture_endpoint_id == "wasapi:capture:ghi"
    assert loaded.call_bridge.local_headphones_endpoint_id == "wasapi:render:jkl"
