"""Settings migration: backups, saving, the app error path and the WI-09 Mandarin voice.

Split from ``test_config_migration.py`` (CAP-0169 contract.md §4.2, spec §4.3, AC-16); the
shared v1 data and the ``settings_dir`` fixture are in ``tests/_config_migration_helpers.py``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lianiq.config import AppConfig
from lianiq.config_migration import (
    backup_legacy_settings,
    legacy_backup_path,
    migrate_settings,
)
from tests._config_migration_helpers import (
    REPO_DEFAULT,
    settings_dir_fixture,  # noqa: F401
)


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


# --- WI-09: Mandarin placeholder -> pinned sherpa-onnx voice --------------------------------

SHERPA_VOICE = "models/sherpa/vits-icefall-zh-aishell3"
SHERPA_ENGINE = {"engine": "sherpa-onnx", "speaker_id": 20, "length_scale": 1.15, "num_threads": 4}


def test_v2_overlay_saved_before_engine_selection_maps_the_placeholder_to_sherpa() -> None:
    saved = {
        "schema_version": 2,
        "tts": {
            "voices": {
                "de": "models/piper/de_DE-thorsten-medium.onnx",
                "zh-Hans": "models/piper/zh_CN-user-provided.onnx",
            },
            "length_scale": 1.0,
            "device": "auto",
        },
    }
    original = json.loads(json.dumps(saved))

    migrated = migrate_settings(saved)

    assert saved == original  # not mutated
    assert migrated["tts"]["voices"]["zh-Hans"] == SHERPA_VOICE
    assert migrated["tts"]["engines"] == {"de": {"engine": "piper"}, "zh-Hans": SHERPA_ENGINE}
    assert migrate_settings(migrated) == migrated  # idempotent


def test_operator_provided_piper_voice_keeps_piper_after_merging_the_new_default(
    settings_dir: Path,
) -> None:
    (settings_dir / "settings.json").write_text(REPO_DEFAULT.read_text("utf-8"), "utf-8")
    overlay = {
        "schema_version": 2,
        "tts": {"voices": {"zh-Hans": "D:/voices/zh_CN-licensed.onnx"}},
    }
    (settings_dir / "settings.local.json").write_text(json.dumps(overlay), "utf-8")

    config = AppConfig.load()

    assert config.tts.voices["zh-Hans"] == "D:/voices/zh_CN-licensed.onnx"
    assert config.tts.engines["zh-Hans"].engine == "piper"
    assert config.tts.engines["de"].engine == "piper"


def test_old_overlay_with_the_placeholder_loads_the_sherpa_voice(settings_dir: Path) -> None:
    (settings_dir / "settings.json").write_text(REPO_DEFAULT.read_text("utf-8"), "utf-8")
    overlay = {
        "tts": {"zh_voice_path": r"models\piper\zh_CN-user-provided.onnx"}
    }  # v1, Windows separators
    (settings_dir / "settings.local.json").write_text(json.dumps(overlay), "utf-8")

    config = AppConfig.load()

    assert config == AppConfig.load(REPO_DEFAULT)
    assert config.tts.voices["zh-Hans"] == SHERPA_VOICE
    assert config.tts.engines["zh-Hans"].engine == "sherpa-onnx"


def test_file_with_engine_selection_is_left_unchanged() -> None:
    document = {
        "schema_version": 2,
        "tts": {
            "voices": {"zh-Hans": "models/piper/zh_CN-user-provided.onnx"},
            "engines": {"zh-Hans": {"engine": "piper"}},
        },
    }

    assert migrate_settings(document) == document
