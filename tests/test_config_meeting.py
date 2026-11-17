"""CAP-0177 WI-02: the eleven optional ``meeting.*`` settings keys (meeting contract.md §8)."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pytest

import lianiq.config as config_module
from lianiq.audio.device_selection import DeviceChoice, DevicePolicy, resolve_choice
from lianiq.config import AppConfig
from tests._fake_devices import CAPTURE, mic

MEETING_DEFAULTS = {
    "local_language": "de",
    "table_capture_endpoint_id": None,
    "table_render_endpoint_id": None,
    "user_input_policy": "follow_default",
    "user_input_endpoint_id": None,
    "local_output_endpoint_id": None,
    "local_output_is_headset": False,
    "speak_local": False,
    "table_input_during_output": "mute",
    "guard_tail_ms": 300,
    "max_playback_defer_ms": 5_000,
}


def test_meeting_defaults_apply_to_files_without_a_meeting_block(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text('{"schema_version": 2, "audio": {"start_rms": 0.02}}', encoding="utf-8")

    loaded = AppConfig.load(path)
    repository_default = AppConfig.load(config_module.DEFAULT_CONFIG_PATH)

    assert asdict(loaded.meeting) == MEETING_DEFAULTS
    assert loaded.meeting == AppConfig().meeting == repository_default.meeting
    assert loaded.schema_version == 2
    assert loaded.audio.start_rms == 0.02


def test_partial_meeting_block_keeps_the_other_defaults() -> None:
    config = AppConfig.from_mapping({"meeting": {"table_input_during_output": "open"}})

    assert config.meeting.table_input_during_output == "open"
    assert config.meeting.guard_tail_ms == 300
    assert config.meeting.user_input_policy == "follow_default"


def test_ac22_meeting_choices_persist_only_to_the_local_overlay(
    tmp_path: Path, monkeypatch
) -> None:
    default_path = tmp_path / "settings.json"
    local_path = tmp_path / "settings.local.json"
    default_path.write_text('{"schema_version": 2}', encoding="utf-8")
    monkeypatch.setattr(config_module, "DEFAULT_CONFIG_PATH", default_path)
    monkeypatch.setattr(config_module, "LOCAL_CONFIG_PATH", local_path)
    config = AppConfig.load()
    config.meeting.table_capture_endpoint_id = "wasapi:capture:table"
    config.meeting.table_render_endpoint_id = "wasapi:render:table"
    config.meeting.user_input_policy = "explicit"
    config.meeting.user_input_endpoint_id = "wasapi:capture:headset"
    config.meeting.local_output_endpoint_id = "wasapi:render:headset"
    config.meeting.local_output_is_headset = True
    config.meeting.speak_local = True
    config.meeting.table_input_during_output = "open"
    config.meeting.guard_tail_ms = 0
    config.meeting.max_playback_defer_ms = 15_000

    config.save()
    reloaded = AppConfig.load()

    assert reloaded.meeting == config.meeting
    assert reloaded.meeting.user_input_policy == "explicit"
    assert reloaded.meeting.user_input_endpoint_id == "wasapi:capture:headset"
    saved = json.loads(local_path.read_text(encoding="utf-8"))
    assert saved["schema_version"] == 2
    assert saved["meeting"]["table_input_during_output"] == "open"
    assert default_path.read_text(encoding="utf-8") == '{"schema_version": 2}'


@pytest.mark.parametrize(
    ("meeting", "key"),
    [
        ({"local_language": ""}, "meeting.local_language"),
        ({"table_capture_endpoint_id": 7}, "meeting.table_capture_endpoint_id"),
        ({"table_render_endpoint_id": ["x"]}, "meeting.table_render_endpoint_id"),
        ({"user_input_policy": "always"}, "meeting.user_input_policy"),
        ({"user_input_policy": None}, "meeting.user_input_policy"),
        ({"user_input_endpoint_id": 1}, "meeting.user_input_endpoint_id"),
        ({"local_output_endpoint_id": 1.5}, "meeting.local_output_endpoint_id"),
        ({"local_output_is_headset": "yes"}, "meeting.local_output_is_headset"),
        ({"speak_local": 1}, "meeting.speak_local"),
        ({"table_input_during_output": "loud"}, "meeting.table_input_during_output"),
        ({"table_input_during_output": "MUTE"}, "meeting.table_input_during_output"),
        ({"guard_tail_ms": -1}, "meeting.guard_tail_ms"),
        ({"guard_tail_ms": 2_001}, "meeting.guard_tail_ms"),
        ({"guard_tail_ms": 300.0}, "meeting.guard_tail_ms"),
        ({"guard_tail_ms": True}, "meeting.guard_tail_ms"),
        ({"max_playback_defer_ms": 999}, "meeting.max_playback_defer_ms"),
        ({"max_playback_defer_ms": 15_001}, "meeting.max_playback_defer_ms"),
    ],
)
def test_invalid_meeting_settings_fail_the_load_with_the_key_named(meeting: dict, key: str) -> None:
    with pytest.raises(ValueError, match=key.replace(".", r"\.")):
        AppConfig.from_mapping({"schema_version": 2, "meeting": meeting})


@pytest.mark.parametrize(
    "meeting",
    [
        {"guard_tail_ms": 0},
        {"guard_tail_ms": 2_000},
        {"max_playback_defer_ms": 1_000},
        {"max_playback_defer_ms": 15_000},
        {"local_language": "zh-Hans", "user_input_policy": "explicit"},
    ],
)
def test_meeting_range_bounds_are_inclusive(meeting: dict) -> None:
    config = AppConfig.from_mapping({"meeting": meeting})

    for name, value in meeting.items():
        assert getattr(config.meeting, name) == value


def test_ac01_user_microphone_follows_the_windows_default_unless_explicit() -> None:
    laptop = mic("Laptop microphone", 1, "laptop")
    table = mic("Table speakerphone", 2, "table")
    headset = mic("USB Headset", 3, "headset")
    inventory = [laptop, table, headset]

    def resolved(meeting: dict, default):
        settings = AppConfig.from_mapping({"meeting": meeting}).meeting
        choice = DeviceChoice(
            DevicePolicy(settings.user_input_policy), settings.user_input_endpoint_id
        )
        return resolve_choice(choice, inventory, CAPTURE, default).endpoint

    assert resolved({}, laptop) == laptop
    # Following the default can resolve to the table microphone: the page then reports the
    # conflict (row 8 lists "your microphone"), see test_requirements_meeting.py.
    assert resolved({}, table).endpoint_id == table.endpoint_id
    explicit = {"user_input_policy": "explicit", "user_input_endpoint_id": headset.endpoint_id}
    assert resolved(explicit, laptop) == headset
    assert resolved(explicit, table) == headset
