"""Per-language voice output settings ``tts.output`` (CAP-0167 contract.md §6, spec §4.1, AC-20).

The file-level load and rejection cases are in ``test_config_migration.py``.
"""

from __future__ import annotations

import pytest

from lianiq.config import AppConfig, TtsConfig
from lianiq.config_voice import VoiceOutputPreference, VoicePreferences
from lianiq.languages import BUILTIN_REGISTRY, LanguageId
from lianiq.tts.voice_controls import VoiceOptions

DE = LanguageId("de")
ZH = LanguageId("zh-Hans")


def test_default_preference_reproduces_todays_synthesis() -> None:
    preference = VoiceOutputPreference()

    assert (preference.enabled, preference.speaker) == (None, None)
    assert preference.options() == VoiceOptions()
    assert VoiceOutputPreference(True, 3, 1.1, 0.5).options() == VoiceOptions(3, 1.1, 0.5)


@pytest.mark.parametrize(
    "values",
    [
        {"enabled": "yes"},
        {"enabled": 1},
        {"speaker": -1},
        {"rate": 2.0},
        {"volume": 0.0},
    ],
)
def test_invalid_preference_values_are_rejected(values: dict) -> None:
    with pytest.raises(ValueError):
        VoiceOutputPreference(**values)


def test_tts_output_mappings_become_preferences() -> None:
    tts = TtsConfig(output={"de": {"enabled": False, "rate": 1.25}})

    assert tts.output == {"de": VoiceOutputPreference(enabled=False, rate=1.25)}
    assert TtsConfig().output == {}
    with pytest.raises(ValueError):
        TtsConfig(output={"de": {"volume": 3}})


def test_preferences_default_until_set_and_keyed_by_language_id() -> None:
    config = AppConfig()
    preferences = VoicePreferences(config, BUILTIN_REGISTRY)

    assert preferences.get(DE) == VoiceOutputPreference()
    assert preferences.options("zh-hans") == VoiceOptions()
    assert config.tts.output == {}

    preferences.set_enabled("zh-hans", False)
    preferences.set_options(ZH, VoiceOptions(speaker=0, rate=1.1))
    preferences.set_options(DE, VoiceOptions(volume=0.4))
    preferences.set_enabled(DE, True)

    assert config.tts.output == {
        ZH: VoiceOutputPreference(enabled=False, speaker=0, rate=1.1),
        DE: VoiceOutputPreference(enabled=True, volume=0.4),
    }
    assert preferences.options(ZH) == VoiceOptions(speaker=0, rate=1.1)
    with pytest.raises(TypeError):
        preferences.set_enabled(DE, None)  # type: ignore[arg-type]


def test_sync_output_writes_languages_output_from_the_plan() -> None:
    config = AppConfig()
    preferences = VoicePreferences(config, BUILTIN_REGISTRY)

    preferences.sync_output(frozenset({DE}))
    assert config.languages.output == "spoken"
    preferences.sync_output(frozenset())
    assert config.languages.output == "text"


def test_preferences_round_trip_through_the_local_file(tmp_path) -> None:
    path = tmp_path / "settings.local.json"
    config = AppConfig()
    VoicePreferences(config, BUILTIN_REGISTRY).set_options(ZH, VoiceOptions(31, 1.1, 1.0))
    config.save(path)

    loaded = AppConfig.load(path)

    assert loaded == config
    assert loaded.tts.output[ZH] == VoiceOutputPreference(speaker=31, rate=1.1)
