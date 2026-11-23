"""CAP-0170 AC-20: the optional ``listen.*`` settings block."""

from __future__ import annotations

import pytest

from lianiq.config import SCHEMA_VERSION, AppConfig
from lianiq.config_listen import ListenConfig


def test_ac20_a_file_without_listen_loads_with_the_defaults() -> None:
    config = AppConfig.from_mapping({"schema_version": 2})
    assert config.listen == ListenConfig()
    assert config.schema_version == SCHEMA_VERSION == 2


def test_ac20_an_invalid_input_policy_fails_naming_its_key() -> None:
    with pytest.raises(ValueError, match=r"listen\.input_policy"):
        AppConfig.from_mapping({"listen": {"input_policy": "loudest"}})


def test_a_saved_block_round_trips(tmp_path) -> None:
    config = AppConfig()
    config.listen = ListenConfig("zh-Hans", "de", "explicit", "{mic}")
    path = tmp_path / "settings.local.json"
    config.save(path)
    assert AppConfig.load(path).listen == config.listen
