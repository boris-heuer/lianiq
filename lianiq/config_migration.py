"""Settings schema v1 -> v2 migration (CAP-0169 contract.md §4.2, spec §4.3).

Each settings file (repository default, local overlay) is migrated on its own, in
memory, before the files are merged, so a legacy overlay never collides with v2
defaults. A migrated file contains only the values its source file had; defaults come
from the dataclasses in :mod:`lianiq.config`. Nothing is written here except the
one-time byte-exact backup of a legacy file that :meth:`AppConfig.save` is about to
replace.
"""

from __future__ import annotations

import copy
import json
import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from lianiq.languages.errors import SettingsMigrationError

__all__ = [
    "LEGACY_GLOSSARY_EDGES",
    "SCHEMA_VERSION",
    "SettingsMigrationError",
    "backup_legacy_settings",
    "is_current_schema",
    "languages_from_legacy_mode",
    "legacy_backup_path",
    "legacy_mode_from_languages",
    "migrate_settings",
    "read_settings_file",
]

SCHEMA_VERSION = 2

# Legacy glossary direction keys (lianiq before CAP-0169 WI-03) and the directed edge
# each one maps to on load (contract.md §3.1.7).
LEGACY_GLOSSARY_EDGES: Mapping[str, str] = {
    "de-zh": "de>zh-Hans",
    "zh-de": "zh-Hans>de",
}

# Frozen snapshot of the schema v1 keys (lianiq before CAP-0169 WI-02). Any other key
# in a v1 file is not mappable and raises instead of being dropped silently.
_V1_KEYS: dict[str, frozenset[str]] = {
    "audio": frozenset(
        {
            "sample_rate",
            "chunk_ms",
            "start_rms",
            "end_silence_ms",
            "pre_roll_ms",
            "min_speech_ms",
            "max_speech_seconds",
            "input_device",
            "output_device",
        }
    ),
    "speech_to_text": frozenset(
        {"model_path", "device", "compute_type", "cpu_threads", "beam_size"}
    ),
    "translation": frozenset(
        {
            "de_zh_model_path",
            "zh_de_model_path",
            "cpu_threads",
            "device",
            "context_sentences",
            "glossary_path",
        }
    ),
    "tts": frozenset(
        {"enabled", "de_voice_path", "zh_voice_path", "length_scale", "device", "use_cuda"}
    ),
    "ui": frozenset({"mode", "log_level"}),
    "call_bridge": frozenset(
        {
            "enabled",
            "local_microphone_endpoint_id",
            "call_microphone_render_endpoint_id",
            "call_speaker_capture_endpoint_id",
            "local_headphones_endpoint_id",
            "failure_policy",
            "max_pending_age_ms",
        }
    ),
}

_LEGACY_EDGES = {
    "de_zh_model_path": "de>zh-Hans",
    "zh_de_model_path": "zh-Hans>de",
}
_LEGACY_VOICES = {
    "de_voice_path": "de",
    "zh_voice_path": "zh-Hans",
}
# v1 ``ui.mode`` -> v2 (``languages.routing``, ``languages.fixed_source``).
_LEGACY_UI_MODES: dict[str, tuple[str, str | None]] = {
    "auto": ("bidirectional", None),
    "de-zh": ("fixed", "de"),
    "zh-de": ("fixed", "zh-Hans"),
}


def is_current_schema(raw: object) -> bool:
    """Return whether ``raw`` is a settings document of the current schema."""
    return isinstance(raw, Mapping) and _is_schema_version(raw.get("schema_version"))


def migrate_settings(raw: object) -> dict[str, Any]:
    """Return the schema v2 form of one settings document without mutating it.

    A v2 document is returned as a copy. A document without ``schema_version`` is v1
    and is mapped key by key (contract.md §4.2). Raises :class:`SettingsMigrationError`
    naming the first key that cannot be mapped.
    """
    if not isinstance(raw, Mapping):
        raise SettingsMigrationError("(root)")
    if "schema_version" in raw:
        if not _is_schema_version(raw["schema_version"]):
            raise SettingsMigrationError("schema_version")
        return copy.deepcopy(dict(raw))
    return _migrate_v1(raw)


def read_settings_file(path: Path) -> dict[str, Any]:
    """Read one settings file and return its migrated v2 form (``{}`` if absent)."""
    if not path.exists():
        return {}
    return migrate_settings(json.loads(path.read_text(encoding="utf-8")))


def legacy_backup_path(path: Path) -> Path:
    """``settings.local.json`` -> ``settings.local.v1.json`` next to it."""
    return path.with_name(f"{path.stem}.v1{path.suffix}")


def backup_legacy_settings(path: Path) -> Path | None:
    """Copy a not-yet-v2 settings file once, byte for byte, before it is replaced.

    Returns the backup path when a backup was written. An existing backup is never
    overwritten, so it keeps the first original; a v2 or absent file is not copied.
    """
    if not path.exists():
        return None
    try:
        current = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        current = None
    if is_current_schema(current):
        return None
    backup = legacy_backup_path(path)
    if backup.exists():
        return None
    shutil.copyfile(path, backup)
    return backup


def languages_from_legacy_mode(mode: str) -> tuple[str, str | None]:
    """Map a v1 ``ui.mode`` value to v2 ``(routing, fixed_source)``."""
    try:
        return _LEGACY_UI_MODES[mode]
    except (KeyError, TypeError):
        raise SettingsMigrationError("ui.mode") from None


def legacy_mode_from_languages(routing: str, fixed_source: str | None) -> str:
    """Inverse of :func:`languages_from_legacy_mode` for the de/zh-Hans compatibility UI."""
    for mode, target in _LEGACY_UI_MODES.items():
        if target == (routing, fixed_source):
            return mode
    raise ValueError(
        f"No legacy conversation mode for routing={routing!r}, fixed_source={fixed_source!r}"
    )


def _is_schema_version(value: object) -> bool:
    return type(value) is int and value == SCHEMA_VERSION


def _migrate_v1(raw: Mapping[str, Any]) -> dict[str, Any]:
    for section, values in raw.items():
        if section not in _V1_KEYS or not isinstance(values, Mapping):
            raise SettingsMigrationError(str(section))
        for key in values:
            if key not in _V1_KEYS[section]:
                raise SettingsMigrationError(f"{section}.{key}")

    result: dict[str, Any] = {"schema_version": SCHEMA_VERSION}
    languages: dict[str, Any] = {}

    for section in ("audio", "speech_to_text", "call_bridge"):
        if section in raw:
            result[section] = copy.deepcopy(dict(raw[section]))

    if "translation" in raw:
        translation = copy.deepcopy(dict(raw["translation"]))
        edges = {
            edge: {"model_path": _path_value(translation.pop(key), f"translation.{key}")}
            for key, edge in _LEGACY_EDGES.items()
            if key in translation
        }
        if edges:
            translation = {"edges": edges, **translation}
        result["translation"] = translation

    if "tts" in raw:
        tts = copy.deepcopy(dict(raw["tts"]))
        voices = {
            language: _path_value(tts.pop(key), f"tts.{key}")
            for key, language in _LEGACY_VOICES.items()
            if key in tts
        }
        if "enabled" in tts:
            enabled = tts.pop("enabled")
            if not isinstance(enabled, bool):
                raise SettingsMigrationError("tts.enabled")
            languages["output"] = "spoken" if enabled else "text"
        if "use_cuda" in tts:
            use_cuda = tts.pop("use_cuda")
            if not isinstance(use_cuda, bool):
                raise SettingsMigrationError("tts.use_cuda")
            # Existing rule: the legacy flag only applies when the file sets no device.
            tts.setdefault("device", "cuda" if use_cuda else "cpu")
        if voices:
            tts = {"voices": voices, **tts}
        result["tts"] = tts

    if "ui" in raw:
        ui = copy.deepcopy(dict(raw["ui"]))
        if "mode" in ui:
            routing, fixed_source = languages_from_legacy_mode(ui.pop("mode"))
            languages["routing"] = routing
            languages["fixed_source"] = fixed_source
        result["ui"] = ui

    if languages:
        result = {"schema_version": SCHEMA_VERSION, "languages": languages, **result}
    return result


def _path_value(value: object, key: str) -> str:
    if not isinstance(value, str):
        raise SettingsMigrationError(key)
    return value
