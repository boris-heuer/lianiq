"""Shared data and the ``settings_dir`` fixture for the settings migration tests.

Used by ``test_config_migration.py`` and ``test_config_migration_files.py`` (CAP-0169
contract.md §4.2, spec §4.3, AC-16).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import lianiq.config as config_module

REPO_ROOT = Path(__file__).resolve().parent.parent
REPO_DEFAULT = REPO_ROOT / "config" / "settings.json"
LEGACY_LOCAL_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "settings" / "legacy-v1.local.json"

# Byte-for-byte content of config/settings.json before schema v2 (lianiq a2eb139).
TODAYS_V1_DEFAULT = """{
  "audio": {
    "sample_rate": 16000,
    "chunk_ms": 30,
    "start_rms": 0.018,
    "end_silence_ms": 600,
    "pre_roll_ms": 180,
    "min_speech_ms": 240,
    "max_speech_seconds": 12.0,
    "input_device": null,
    "output_device": null
  },
  "speech_to_text": {
    "model_path": "models/faster-whisper-small",
    "device": "auto",
    "compute_type": "int8",
    "cpu_threads": 8,
    "beam_size": 1
  },
  "translation": {
    "de_zh_model_path": "models/opus-mt-de-zh",
    "zh_de_model_path": "models/opus-mt-zh-de",
    "cpu_threads": 8,
    "device": "auto",
    "context_sentences": 5,
    "glossary_path": "config/glossary.json"
  },
  "tts": {
    "enabled": false,
    "de_voice_path": "models/piper/de_DE-thorsten-medium.onnx",
    "zh_voice_path": "models/piper/zh_CN-user-provided.onnx",
    "length_scale": 1.0,
    "device": "auto"
  },
  "ui": {
    "mode": "auto",
    "log_level": "INFO"
  },
  "call_bridge": {
    "enabled": false,
    "local_microphone_endpoint_id": null,
    "call_microphone_render_endpoint_id": null,
    "call_speaker_capture_endpoint_id": null,
    "local_headphones_endpoint_id": null,
    "failure_policy": "mute",
    "max_pending_age_ms": 4000
  }
}
"""

# Independent oracle of contract.md §4.2: v1 location -> (v2 location, value transform).
V1_TO_V2_PATHS: dict[tuple[str, str], tuple[tuple[Any, ...], Any]] = {
    ("translation", "de_zh_model_path"): (
        ("translation", "edges", "de>zh-Hans", "model_path"),
        None,
    ),
    ("translation", "zh_de_model_path"): (
        ("translation", "edges", "zh-Hans>de", "model_path"),
        None,
    ),
    ("tts", "de_voice_path"): (("tts", "voices", "de"), None),
    # WI-09: the Mandarin placeholder voice maps to the pinned sherpa-onnx voice directory.
    ("tts", "zh_voice_path"): (
        ("tts", "voices", "zh-Hans"),
        lambda value: (
            "models/sherpa/vits-icefall-zh-aishell3"
            if value == "models/piper/zh_CN-user-provided.onnx"
            else value
        ),
    ),
    ("tts", "enabled"): (("languages", "output"), {True: "spoken", False: "text"}),
}
LEGACY_UI_MODE_TARGETS = {
    "auto": {"routing": "bidirectional", "fixed_source": None},
    "de-zh": {"routing": "fixed", "fixed_source": "de"},
    "zh-de": {"routing": "fixed", "fixed_source": "zh-Hans"},
}


def _lookup(document: dict[str, Any], path: tuple[Any, ...]) -> Any:
    value: Any = document
    for key in path:
        value = value[key]
    return value


def _assert_every_v1_value_at_its_v2_location(
    legacy: dict[str, Any], migrated: dict[str, Any]
) -> None:
    for section, values in legacy.items():
        for key, value in values.items():
            if (section, key) == ("ui", "mode"):
                for v2_key, expected in LEGACY_UI_MODE_TARGETS[value].items():
                    assert migrated["languages"][v2_key] == expected, (section, key)
                continue
            target, transform = V1_TO_V2_PATHS.get((section, key), ((section, key), None))
            if callable(transform):
                expected = transform(value)
            else:
                expected = transform[value] if transform else value
            assert _lookup(migrated, target) == expected, (section, key)


# The explicit name keeps the fixture "settings_dir" for tests importing it under this name.
@pytest.fixture(name="settings_dir")
def settings_dir_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(config_module, "DEFAULT_CONFIG_PATH", tmp_path / "settings.json")
    monkeypatch.setattr(config_module, "LOCAL_CONFIG_PATH", tmp_path / "settings.local.json")
    return tmp_path
