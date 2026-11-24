"""CAP-0181 AC-04: saved settings gain the English defaults on load (spec §3.2)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import lianiq.config as config_module
from lianiq.config import AppConfig, TranslationEdgeConfig


def test_ac04_saved_settings_gain_the_english_defaults(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "settings.local.json"
    custom = {"model_path": "models/custom-de-zh"}
    path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "speech_to_text": {"languages": ["de", "zh-Hans"]},
                "translation": {"edges": {"de>zh-Hans": custom}},
                "tts": {"voices": {"de": "models/piper/custom.onnx"}},
            }
        ),
        encoding="utf-8",
    )
    default = tmp_path / "settings.json"
    default.write_bytes(config_module.DEFAULT_CONFIG_PATH.read_bytes())
    monkeypatch.setattr(config_module, "DEFAULT_CONFIG_PATH", default)
    monkeypatch.setattr(config_module, "LOCAL_CONFIG_PATH", path)
    config = AppConfig.load()

    assert config.speech_to_text.languages == ["de", "zh-Hans", "en"]
    edges = config.translation.edges
    assert edges["en>zh-Hans"] == TranslationEdgeConfig("models/opus-mt-en-zh", ">>cmn_Hans<<")
    assert edges["zh-Hans>en"] == TranslationEdgeConfig("models/opus-mt-zh-en")
    assert edges["de>zh-Hans"] == TranslationEdgeConfig("models/custom-de-zh")
    assert config.tts.voices["de"] == "models/piper/custom.onnx"
    assert config.tts.voices["en"].endswith("piper-en_US-ljspeech-high/en_US-ljspeech-high.onnx")
    assert config.tts.engines["en"].engine == "piper"
    with pytest.raises(ValueError, match="target_prefix"):
        TranslationEdgeConfig("models/x", "cmn_Hans")
