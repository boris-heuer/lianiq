"""Settings schema v1 -> v2 migration (CAP-0169 contract.md §4.2, spec §4.3, AC-16)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import lianiq.config as config_module
from lianiq.config import AppConfig
from lianiq.config_migration import (
    SettingsMigrationError,
    backup_legacy_settings,
    legacy_backup_path,
    migrate_settings,
)

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
    ("tts", "zh_voice_path"): (("tts", "voices", "zh-Hans"), None),
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
            expected = transform[value] if transform else value
            assert _lookup(migrated, target) == expected, (section, key)


@pytest.fixture
def settings_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(config_module, "DEFAULT_CONFIG_PATH", tmp_path / "settings.json")
    monkeypatch.setattr(config_module, "LOCAL_CONFIG_PATH", tmp_path / "settings.local.json")
    return tmp_path


def test_ac16_todays_v1_default_migrates_to_the_shipped_v2_default() -> None:
    legacy = json.loads(TODAYS_V1_DEFAULT)
    shipped = json.loads(REPO_DEFAULT.read_text(encoding="utf-8"))

    assert shipped["schema_version"] == 2
    assert migrate_settings(shipped) == shipped
    _assert_every_v1_value_at_its_v2_location(legacy, shipped)
    assert shipped["languages"] == {
        "pair": ["de", "zh-Hans"],
        "routing": "bidirectional",
        "fixed_source": None,
        "output": "text",
        "detection_min_probability": 0.7,
    }
    assert shipped["speech_to_text"]["languages"] == ["de", "zh-Hans"]
    assert shipped["call_bridge"]["local_language"] == "de"
    assert "enabled" not in shipped["tts"]
    assert "mode" not in shipped["ui"]
    # The shipped v2 default is exactly what loading today's v1 default produces.
    assert AppConfig.from_mapping(migrate_settings(legacy)) == AppConfig.load(REPO_DEFAULT)


def test_ac16_legacy_local_overlay_is_migrated_backed_up_once_and_idempotent(
    settings_dir: Path,
) -> None:
    default_path = settings_dir / "settings.json"
    local_path = settings_dir / "settings.local.json"
    default_bytes = REPO_DEFAULT.read_bytes()
    fixture_bytes = LEGACY_LOCAL_FIXTURE.read_bytes()
    default_path.write_bytes(default_bytes)
    local_path.write_bytes(fixture_bytes)
    legacy = json.loads(fixture_bytes)

    first = AppConfig.load()
    first.save()

    saved = json.loads(local_path.read_text(encoding="utf-8"))
    assert saved["schema_version"] == 2
    _assert_every_v1_value_at_its_v2_location(legacy, saved)
    # Values the overlay did not set keep the repository defaults.
    assert saved["translation"]["glossary_path"] == "config/glossary.json"
    assert saved["languages"]["pair"] == ["de", "zh-Hans"]
    assert saved["call_bridge"]["local_language"] == "de"
    assert first.legacy_mode == "zh-de"
    assert first.voice_output is True

    backup = settings_dir / "settings.local.v1.json"
    assert backup.read_bytes() == fixture_bytes
    assert default_path.read_bytes() == default_bytes

    second = AppConfig.load()
    assert second == first
    saved_bytes = local_path.read_bytes()
    second.save()
    assert local_path.read_bytes() == saved_bytes
    assert backup.read_bytes() == fixture_bytes
    assert default_path.read_bytes() == default_bytes


def test_ac16_v1_default_and_v1_overlay_are_migrated_separately_then_merged(
    settings_dir: Path,
) -> None:
    (settings_dir / "settings.json").write_text(TODAYS_V1_DEFAULT, encoding="utf-8")
    (settings_dir / "settings.local.json").write_bytes(LEGACY_LOCAL_FIXTURE.read_bytes())

    config = AppConfig.load()

    assert config.languages.routing == "fixed"
    assert config.languages.fixed_source == "zh-Hans"
    assert config.languages.output == "spoken"
    assert config.translation.edges["zh-Hans>de"].model_path == "models/custom/opus-mt-zh-de"
    assert config.translation.edges["de>zh-Hans"].model_path == "models/opus-mt-de-zh"
    assert config.tts.voices == {
        "de": "models/custom/de_DE-custom.onnx",
        "zh-Hans": "models/custom/zh_CN-custom.onnx",
    }
    assert config.audio.sample_rate == 16_000
    assert config.audio.start_rms == 0.021


@pytest.mark.parametrize(
    ("local_document", "key"),
    [
        ({"ui": {"mode": "en-de"}}, "ui.mode"),
        ({"tts": {"enabled": "yes"}}, "tts.enabled"),
        ({"tts": {"use_cuda": "true"}}, "tts.use_cuda"),
        ({"translation": {"de_zh_model_path": 7}}, "translation.de_zh_model_path"),
        ({"translation": {"fr_de_model_path": "models/x"}}, "translation.fr_de_model_path"),
        ({"languages": {"pair": ["de", "en"]}}, "languages"),
        ({"tts": "off"}, "tts"),
        ({"schema_version": 3}, "schema_version"),
    ],
)
def test_ac16_unmappable_value_raises_naming_the_key_and_leaves_files_unchanged(
    settings_dir: Path, local_document: dict[str, Any], key: str
) -> None:
    default_path = settings_dir / "settings.json"
    local_path = settings_dir / "settings.local.json"
    default_path.write_bytes(REPO_DEFAULT.read_bytes())
    local_bytes = json.dumps(local_document).encode("utf-8")
    local_path.write_bytes(local_bytes)

    with pytest.raises(SettingsMigrationError) as raised:
        AppConfig.load()

    assert raised.value.key == key
    assert key in str(raised.value)
    assert local_path.read_bytes() == local_bytes
    assert default_path.read_bytes() == REPO_DEFAULT.read_bytes()
    assert not (settings_dir / "settings.local.v1.json").exists()


@pytest.mark.parametrize(("mode", "expected"), list(LEGACY_UI_MODE_TARGETS.items()))
def test_legacy_ui_mode_maps_to_routing_and_fixed_source(
    mode: str, expected: dict[str, Any]
) -> None:
    migrated = migrate_settings({"ui": {"mode": mode, "log_level": "INFO"}})

    assert migrated == {"schema_version": 2, "languages": expected, "ui": {"log_level": "INFO"}}


def test_partial_legacy_overlay_adds_no_v2_defaults() -> None:
    overlay = {"call_bridge": {"enabled": True, "local_microphone_endpoint_id": "id"}}

    assert migrate_settings(overlay) == {"schema_version": 2, **overlay}


def test_legacy_use_cuda_maps_to_device_unless_the_same_file_sets_device() -> None:
    assert migrate_settings({"tts": {"use_cuda": True}})["tts"] == {"device": "cuda"}
    assert migrate_settings({"tts": {"use_cuda": False}})["tts"] == {"device": "cpu"}
    assert migrate_settings({"tts": {"use_cuda": True, "device": "auto"}})["tts"] == {
        "device": "auto"
    }


def test_v2_document_is_returned_unchanged_and_not_mutated() -> None:
    document = json.loads(REPO_DEFAULT.read_text(encoding="utf-8"))
    snapshot = json.loads(json.dumps(document))

    migrated = migrate_settings(document)

    assert migrated == snapshot
    assert migrated is not document
    assert document == snapshot


def test_existing_backup_is_never_overwritten(tmp_path: Path) -> None:
    local_path = tmp_path / "settings.local.json"
    local_path.write_text('{"ui": {"mode": "de-zh"}}', encoding="utf-8")
    backup = legacy_backup_path(local_path)
    assert backup == tmp_path / "settings.local.v1.json"
    backup.write_text("first original", encoding="utf-8")

    assert backup_legacy_settings(local_path) is None
    assert backup.read_text(encoding="utf-8") == "first original"


def test_v2_file_is_not_backed_up(tmp_path: Path) -> None:
    local_path = tmp_path / "settings.local.json"
    AppConfig().save(local_path)

    assert backup_legacy_settings(local_path) is None
    assert not legacy_backup_path(local_path).exists()


def test_save_never_writes_the_repository_default(settings_dir: Path) -> None:
    default_path = settings_dir / "settings.json"
    default_path.write_bytes(REPO_DEFAULT.read_bytes())

    with pytest.raises(ValueError, match="repository default"):
        AppConfig().save(default_path)

    assert default_path.read_bytes() == REPO_DEFAULT.read_bytes()


def test_app_shows_the_migration_error_and_writes_nothing(
    settings_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtWidgets import QApplication, QMessageBox

    import lianiq.app as app_module

    application = QApplication.instance() or QApplication([])
    assert application is not None

    local_path = settings_dir / "settings.local.json"
    local_path.write_text('{"ui": {"mode": "en-de"}}', encoding="utf-8")
    shown: list[str] = []
    monkeypatch.setattr(
        QMessageBox, "critical", staticmethod(lambda _parent, _title, text: shown.append(text))
    )

    assert app_module.main() == 2

    assert len(shown) == 1
    assert "ui.mode" in shown[0]
    assert local_path.read_text(encoding="utf-8") == '{"ui": {"mode": "en-de"}}'
    assert not (settings_dir / "settings.local.v1.json").exists()
