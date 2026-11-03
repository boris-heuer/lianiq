from __future__ import annotations

import json
from pathlib import Path

import pytest

import lianiq.config as config_module
from lianiq.config import AppConfig, TranslationEdgeConfig


def test_config_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    config = AppConfig()
    config.audio.start_rms = 0.025
    config.translation.context_sentences = 7
    config.save(path)

    loaded = AppConfig.load(path)
    assert loaded == config
    assert loaded.audio.start_rms == 0.025
    assert loaded.translation.context_sentences == 7
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["schema_version"] == 2
    assert saved["languages"]["output"] == "text"


def test_v2_language_settings_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    config = AppConfig()
    config.languages.routing = "fixed"
    config.languages.fixed_source = "zh-Hans"
    config.languages.output = "spoken"
    config.languages.detection_min_probability = 0.8
    config.translation.edges["de>zh-Hans"] = TranslationEdgeConfig("models/custom-de-zh")
    config.tts.voices["zh-Hans"] = "models/piper/zh.onnx"
    config.call_bridge.local_language = "zh-Hans"
    config.save(path)

    loaded = AppConfig.load(path)

    assert loaded == config
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["translation"]["edges"]["de>zh-Hans"] == {"model_path": "models/custom-de-zh"}
    assert saved["tts"]["voices"]["zh-Hans"] == "models/piper/zh.onnx"


def test_missing_config_uses_hardware_defaults(tmp_path: Path) -> None:
    config = AppConfig.load(tmp_path / "missing.json")
    assert config.speech_to_text.device == "auto"
    assert config.translation.device == "auto"
    assert config.tts.device == "auto"
    assert config.speech_to_text.compute_type == "int8"
    assert config.speech_to_text.cpu_threads == 8
    assert config.speech_to_text.languages == ["de", "zh-Hans"]
    assert config.languages.pair == ["de", "zh-Hans"]
    assert config.languages.detection_min_probability == 0.7
    assert config.call_bridge.local_language == "de"


def test_legacy_tts_cuda_setting_is_migrated(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text('{"tts": {"use_cuda": true}}', encoding="utf-8")

    config = AppConfig.load(path)

    assert config.tts.device == "cuda"


def test_compatibility_accessors_read_v2_values() -> None:
    config = AppConfig()
    config.translation.edges["zh-Hans>de"] = TranslationEdgeConfig("models/custom-zh-de")
    config.tts.voices["de"] = "models/piper/custom-de.onnx"

    assert config.translation.de_zh_model_path == "models/opus-mt-de-zh"
    assert config.translation.zh_de_model_path == "models/custom-zh-de"
    assert config.tts.de_voice_path == "models/piper/custom-de.onnx"
    assert config.tts.zh_voice_path == "models/piper/zh_CN-user-provided.onnx"
    del config.translation.edges["zh-Hans>de"]
    assert config.translation.zh_de_model_path == ""

    assert config.voice_output is False
    config.voice_output = True
    assert config.languages.output == "spoken"

    assert config.legacy_mode == "auto"
    config.legacy_mode = "zh-de"
    assert (config.languages.routing, config.languages.fixed_source) == ("fixed", "zh-Hans")
    config.legacy_mode = "de-zh"
    assert (config.languages.routing, config.languages.fixed_source) == ("fixed", "de")
    config.legacy_mode = "auto"
    assert (config.languages.routing, config.languages.fixed_source) == ("bidirectional", None)


@pytest.mark.parametrize(
    ("languages", "message"),
    [
        ({"pair": ["de", "de"]}, "two different"),
        ({"routing": "alternating"}, "routing"),
        ({"routing": "fixed"}, "fixed_source"),
        ({"fixed_source": "de"}, "fixed_source"),
        ({"routing": "fixed", "fixed_source": "en"}, "member"),
        ({"output": "loud"}, "output"),
        ({"detection_min_probability": 1.5}, "detection_min_probability"),
    ],
)
def test_invalid_v2_language_settings_are_rejected(languages: dict, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        AppConfig.from_mapping({"schema_version": 2, "languages": languages})


def test_default_config_is_overlaid_and_runtime_save_uses_ignored_local_file(
    tmp_path: Path, monkeypatch
) -> None:
    default_path = tmp_path / "settings.json"
    local_path = tmp_path / "settings.local.json"
    default_path.write_text(
        '{"schema_version": 2, "audio": {"start_rms": 0.02}, "call_bridge": {"enabled": false}}',
        encoding="utf-8",
    )
    local_path.write_text(
        '{"schema_version": 2, "call_bridge": '
        '{"enabled": true, "local_microphone_endpoint_id": "private-id"}}',
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
    # A v2 overlay is replaced in place; only a legacy file gets a v1 backup.
    assert not (tmp_path / "settings.local.v1.json").exists()


def test_legacy_partial_overlay_still_overlays_the_default(tmp_path: Path, monkeypatch) -> None:
    default_path = tmp_path / "settings.json"
    local_path = tmp_path / "settings.local.json"
    default_path.write_text('{"audio": {"start_rms": 0.02}}', encoding="utf-8")
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
