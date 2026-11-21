"""Voice status, spoken plan and Start check (CAP-0167 WI-02, contract §4; AC-06, AC-24).

Synthetic languages ``qaa``/``qab`` only; no model, device or display is used.
"""

from __future__ import annotations

from lianiq.config import AppConfig, VoiceEngineConfig
from lianiq.config_voice import VoicePreferences
from lianiq.conversation.spoken_output import (
    VoiceState,
    conversation_output,
    output_languages,
    spoken_plan,
    spoken_requirements,
    start_check,
    voice_status,
)
from lianiq.languages import (
    DeviceReadiness,
    InputKind,
    OutputKind,
    Requirement,
    RequirementKind,
    RoutingKind,
    SessionPair,
    UsageMode,
    check,
)
from lianiq.tts.voice_controls import VoiceOptions
from tests.languages.synthetic import (
    QAA,
    QAB,
    manifest_record,
    provisioned_catalog,
    synthetic_registry,
    write_manifest,
)

REGISTRY = synthetic_registry()
PAIR = REGISTRY.pair(QAA, QAB)


def session(routing=RoutingKind.BIDIRECTIONAL, output=OutputKind.TEXT, fixed_source=None):
    mode = UsageMode(InputKind.MICROPHONE, routing, output)
    return SessionPair(PAIR, mode, fixed_source=fixed_source)


def config_for(*languages) -> AppConfig:
    config = AppConfig()
    config.tts.voices = {language: f"models/voices/{language}.onnx" for language in languages}
    config.tts.engines = {}
    return config


def status(language, catalog, config, outputs):
    return voice_status(
        language, catalog=catalog, config=config, registry=REGISTRY, outputs=outputs
    )


def test_output_languages_are_both_members_or_the_fixed_target() -> None:
    assert output_languages(session()) == {QAA, QAB}
    assert output_languages(session(RoutingKind.FIXED, fixed_source=QAA)) == {QAB}


def test_voice_status_follows_readiness_engine_codes_and_outputs(tmp_path) -> None:
    catalog = provisioned_catalog(tmp_path, REGISTRY, voices=[QAB])
    config = config_for(QAA, QAB)
    both = frozenset({QAA, QAB})

    ready = status(QAB, catalog, config, both)
    assert (ready.state, ready.voice_name) == (VoiceState.READY, QAB)  # the path stem
    assert status(QAA, catalog, config, both).state is VoiceState.MISSING  # not configured
    # A fixed direction: the source language is no output language.
    assert status(QAB, catalog, config, frozenset({QAA})).state is VoiceState.NOT_OUTPUT
    # The configured engine has no engine code for the language: never ready.
    config.tts.engines = {QAB: VoiceEngineConfig("sherpa-onnx")}
    assert status(QAB, catalog, config, both).state is VoiceState.MISSING


def test_voice_status_invalid_and_speaker_suffix(tmp_path) -> None:
    catalog = provisioned_catalog(tmp_path, REGISTRY, voices=[QAA, QAB])
    voice = tmp_path / "models" / "voices" / f"{QAA}.onnx"
    write_manifest(tmp_path, [{**manifest_record(tmp_path, voice), "sha256": "0" * 64}])
    config = config_for(QAA, QAB)
    VoicePreferences(config, REGISTRY).set_options(QAB, VoiceOptions(speaker=2))
    both = frozenset({QAA, QAB})

    assert status(QAA, catalog, config, both).state is VoiceState.INVALID
    assert status(QAB, catalog, config, both).voice_name == f"{QAB} · speaker 3"


def test_spoken_plan_takes_ready_languages_whose_switch_is_not_off(tmp_path) -> None:
    catalog = provisioned_catalog(tmp_path, REGISTRY, voices=[QAA, QAB])
    config = config_for(QAA, QAB)
    both = frozenset({QAA, QAB})
    statuses = [status(language, catalog, config, both) for language in (QAA, QAB)]

    assert spoken_plan(statuses, config) == both  # no stored choice: on when ready
    VoicePreferences(config, REGISTRY).set_enabled(QAA, False)
    assert spoken_plan(statuses, config) == {QAB}
    missing = [status(QAA, provisioned_catalog(tmp_path / "x", REGISTRY), config, both)]
    assert spoken_plan(missing, config_for(QAA)) == frozenset()


def test_conversation_output_and_spoken_requirements() -> None:
    both = frozenset({QAA, QAB})
    assert conversation_output(both, both) is OutputKind.SPOKEN
    assert conversation_output(both, frozenset({QAB})) is OutputKind.TEXT
    assert spoken_requirements(frozenset({QAB, QAA}), REGISTRY) == (
        Requirement(RequirementKind.VOICE, QAA),
        Requirement(RequirementKind.VOICE, QAB),
        Requirement(RequirementKind.PLAYBACK),
    )
    assert spoken_requirements(frozenset(), REGISTRY) == ()


def test_start_check_equals_row_6_with_every_voice_and_adds_the_partial_plan(tmp_path) -> None:
    catalog = provisioned_catalog(
        tmp_path, REGISTRY, recognition=[QAA, QAB], edges=["qaa>qab", "qab>qaa"], voices=[QAB]
    )
    devices = DeviceReadiness(microphone=True, playback=True)
    both = frozenset({QAA, QAB})
    spoken = session(output=OutputKind.SPOKEN)

    assert start_check(session(), both, catalog, devices) == check(spoken, catalog, devices)
    partial = start_check(session(), frozenset({QAB}), catalog, devices)
    assert partial.available  # row 5 plus the qab voice and playback (AC-04)
    no_speakers = start_check(session(), frozenset({QAB}), catalog, DeviceReadiness(True))
    assert no_speakers.missing == (Requirement(RequirementKind.PLAYBACK),)
    assert start_check(session(), frozenset(), catalog, DeviceReadiness(True)).available
