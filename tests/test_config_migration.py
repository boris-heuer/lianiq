"""Settings schema v1 -> v2 migration (CAP-0169 contract.md §4.2, spec §4.3, AC-16).

The shared v1 data and the ``settings_dir`` fixture are in
``tests/_config_migration_helpers.py``; the backup, save and WI-09 voice tests are in
``test_config_migration_files.py``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from lianiq.config import AppConfig
from lianiq.config_migration import SettingsMigrationError, migrate_settings
from tests._config_migration_helpers import (
    LEGACY_LOCAL_FIXTURE,
    LEGACY_UI_MODE_TARGETS,
    REPO_DEFAULT,
    TODAYS_V1_DEFAULT,
    _assert_every_v1_value_at_its_v2_location,
    settings_dir_fixture,  # noqa: F401
)


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
    assert (first.languages.routing, first.languages.fixed_source) == ("fixed", "zh-Hans")
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
