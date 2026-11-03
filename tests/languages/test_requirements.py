from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from synthetic import (
    QAA,
    QAB,
    SpyRecognizer,
    SpySynthesizer,
    SpyTranslator,
    SyntheticTranscript,
    provisioned_catalog,
    synthetic_registry,
)

from lianiq.languages import (
    BUILTIN_REGISTRY,
    CALL_BRIDGE_MODE,
    DeviceReadiness,
    DirectedEdge,
    InputKind,
    LanguageId,
    OutputKind,
    Requirement,
    RequirementKind,
    RoutingKind,
    SessionPair,
    UnsupportedModeError,
    UsageMode,
    check,
    describe,
    requirements,
)
from lianiq.languages.requirements import CALL_ENDPOINT_ROLES, ordered_requirements

DE = LanguageId("de")
ZH = LanguageId("zh-Hans")
ALL_DEVICES = DeviceReadiness(
    microphone=True, playback=True, call_endpoints=frozenset(CALL_ENDPOINT_ROLES)
)
NO_DEVICES = DeviceReadiness()


def mode(input_kind: str, routing: str, output: str) -> UsageMode:
    return UsageMode(InputKind(input_kind), RoutingKind(routing), OutputKind(output))


def fixed(source: str, input_kind: str = "typed", output: str = "text", pair=("de", "zh-Hans")):
    registry = synthetic_registry() if source.startswith("q") else BUILTIN_REGISTRY
    return SessionPair(
        registry.pair(*pair), mode(input_kind, "fixed", output), fixed_source=LanguageId(source)
    )


def bidirectional(output: str = "text") -> SessionPair:
    return SessionPair(
        BUILTIN_REGISTRY.pair("de", "zh-Hans"), mode("microphone", "bidirectional", output)
    )


def stt(language: str) -> Requirement:
    return Requirement(RequirementKind.RECOGNITION, language)


def mt(key: str) -> Requirement:
    return Requirement(RequirementKind.TRANSLATION, key)


def voice(language: str) -> Requirement:
    return Requirement(RequirementKind.VOICE, language)


MICROPHONE = Requirement(RequirementKind.MICROPHONE)
PLAYBACK = Requirement(RequirementKind.PLAYBACK)


def test_ac04_synthetic_asymmetric_edge_only_allows_its_own_direction(tmp_path: Path) -> None:
    registry = synthetic_registry()
    catalog = provisioned_catalog(tmp_path, registry, edges=["qaa>qab"])

    forward = check(fixed("qaa", pair=(QAA, QAB)), catalog, NO_DEVICES)
    reverse = check(fixed("qab", pair=(QAA, QAB)), catalog, NO_DEVICES)

    assert forward.available is True
    assert forward.missing == ()
    assert reverse.available is False
    assert reverse.missing == (mt("qab>qaa"),)
    assert describe(reverse.missing[0], registry) == "translation Synthetic B → Synthetic A"


def test_ac06_typed_spoken_needs_the_target_voice_and_playback(tmp_path: Path) -> None:
    session = fixed("de", output="spoken")
    without_voice = provisioned_catalog(tmp_path / "a", BUILTIN_REGISTRY, edges=["de>zh-Hans"])
    with_voice = provisioned_catalog(
        tmp_path / "b", BUILTIN_REGISTRY, edges=["de>zh-Hans"], voices=["zh-Hans"]
    )

    unavailable = check(session, without_voice, ALL_DEVICES)
    no_playback = check(session, with_voice, DeviceReadiness(microphone=True))
    available = check(session, with_voice, DeviceReadiness(playback=True))

    assert unavailable.available is False
    assert unavailable.missing == (voice("zh-Hans"),)
    assert describe(unavailable.missing[0], BUILTIN_REGISTRY) == "voice Mandarin (Simplified)"
    assert no_playback.missing == (PLAYBACK,)
    assert available.available is True
    assert available.missing == ()


def test_ac07_listen_and_translate_text_needs_no_voice_and_no_reverse_edge(
    tmp_path: Path,
) -> None:
    session = fixed("de", input_kind="microphone")
    catalog = provisioned_catalog(
        tmp_path, BUILTIN_REGISTRY, recognition=["de"], edges=["de>zh-Hans"]
    )

    result = check(session, catalog, DeviceReadiness(microphone=True))

    assert requirements(session) == {stt("de"), mt("de>zh-Hans"), MICROPHONE}
    assert result.available is True
    assert catalog.voice(DE).status.value == "not_configured"
    assert catalog.translation(DirectedEdge(ZH, DE)).status.value == "not_configured"


@pytest.mark.parametrize(
    ("session", "expected"),
    [
        (fixed("de"), [mt("de>zh-Hans")]),
        (fixed("de", output="spoken"), [mt("de>zh-Hans"), voice("zh-Hans"), PLAYBACK]),
        (fixed("zh-Hans", input_kind="microphone"), [stt("zh-Hans"), mt("zh-Hans>de"), MICROPHONE]),
        (
            fixed("de", input_kind="microphone", output="spoken"),
            [stt("de"), mt("de>zh-Hans"), voice("zh-Hans"), MICROPHONE, PLAYBACK],
        ),
        (
            bidirectional(),
            [stt("de"), stt("zh-Hans"), mt("de>zh-Hans"), mt("zh-Hans>de"), MICROPHONE],
        ),
        (
            bidirectional("spoken"),
            [
                stt("de"),
                stt("zh-Hans"),
                mt("de>zh-Hans"),
                mt("zh-Hans>de"),
                voice("de"),
                voice("zh-Hans"),
                MICROPHONE,
                PLAYBACK,
            ],
        ),
        (
            SessionPair(
                BUILTIN_REGISTRY.pair("de", "zh-Hans"), CALL_BRIDGE_MODE, local_language=DE
            ),
            [
                stt("de"),
                stt("zh-Hans"),
                mt("de>zh-Hans"),
                mt("zh-Hans>de"),
                voice("de"),
                voice("zh-Hans"),
                *(
                    Requirement(RequirementKind.CALL_ENDPOINTS, role)
                    for role in CALL_ENDPOINT_ROLES
                ),
            ],
        ),
    ],
    ids=["row1", "row2", "row3", "row4", "row5", "row6", "row7-call-bridge"],
)
def test_requirement_table_rows(session: SessionPair, expected: list[Requirement]) -> None:
    assert ordered_requirements(session) == tuple(expected)
    assert requirements(session) == frozenset(expected)


@pytest.mark.parametrize(
    "session",
    [fixed("de"), fixed("de", input_kind="microphone"), bidirectional()],
    ids=["row1", "row3", "row5"],
)
def test_voice_readiness_never_blocks_text_output_modes(tmp_path: Path, session) -> None:
    catalog = provisioned_catalog(
        tmp_path,
        BUILTIN_REGISTRY,
        recognition=["de", "zh-Hans"],
        edges=["de>zh-Hans", "zh-Hans>de"],
    )

    assert check(session, catalog, ALL_DEVICES).available is True


def test_check_names_every_missing_requirement_in_order(tmp_path: Path) -> None:
    catalog = provisioned_catalog(
        tmp_path, BUILTIN_REGISTRY, recognition=["de"], edges=["de>zh-Hans"]
    )
    session = SessionPair(
        BUILTIN_REGISTRY.pair("de", "zh-Hans"), CALL_BRIDGE_MODE, local_language=ZH
    )
    devices = DeviceReadiness(call_endpoints=frozenset(CALL_ENDPOINT_ROLES[:3]))

    result = check(session, catalog, devices)

    assert result.available is False
    assert result.missing == (
        stt("zh-Hans"),
        mt("zh-Hans>de"),
        voice("de"),
        voice("zh-Hans"),
        Requirement(RequirementKind.CALL_ENDPOINTS, "local_headphones"),
    )
    assert [describe(item, BUILTIN_REGISTRY) for item in result.missing] == [
        "speech recognition Mandarin (Simplified)",
        "translation Mandarin (Simplified) → German",
        "voice German",
        "voice Mandarin (Simplified)",
        "local headphones endpoint",
    ]
    assert describe(MICROPHONE, BUILTIN_REGISTRY) == "microphone"


def test_invalid_mode_combinations_raise_unsupported_mode() -> None:
    pair = BUILTIN_REGISTRY.pair("de", "zh-Hans")
    with pytest.raises(UnsupportedModeError):
        SessionPair(pair, mode("typed", "bidirectional", "text"))
    with pytest.raises(UnsupportedModeError):
        SessionPair(pair, mode("typed", "fixed", "text"))
    with pytest.raises(UnsupportedModeError):
        SessionPair(pair, mode("typed", "fixed", "text"), fixed_source=LanguageId("en"))
    with pytest.raises(UnsupportedModeError):
        SessionPair(pair, mode("microphone", "bidirectional", "text"), fixed_source=DE)
    with pytest.raises(UnsupportedModeError):
        SessionPair(pair, CALL_BRIDGE_MODE)
    with pytest.raises(UnsupportedModeError):
        SessionPair(pair, mode("microphone", "bidirectional", "text"), local_language=DE)
    with pytest.raises(UnsupportedModeError):
        UsageMode(InputKind.TYPED, RoutingKind.FIXED, OutputKind.TEXT, call_bridge=True)


def test_session_pair_reports_the_fixed_target() -> None:
    assert fixed("zh-Hans").fixed_target == "de"
    assert bidirectional().fixed_target is None


def test_synthetic_spy_adapters_record_calls() -> None:
    recognizer = SpyRecognizer([SyntheticTranscript("hello", "qaa", 0.9, 1.0)])
    translator = SpyTranslator()
    synthesizer = SpySynthesizer()
    edge = DirectedEdge(QAA, QAB)

    transcript = recognizer.transcribe(np.zeros(16, dtype=np.float32), 16_000, language=QAA)
    translator.warm_up([edge])
    translated = translator.translate(transcript.text, edge)
    synthesizer.warm_up([QAB])
    wav = synthesizer.synthesize(translated, QAB)

    assert recognizer.calls == ["qaa"]
    assert recognizer.warmed_up is False
    assert translator.warmed_edges == ["qaa>qab"]
    assert translator.calls == [("hello", "qaa>qab", ())]
    assert translated == "[qaa>qab] hello"
    assert synthesizer.calls == [("[qaa>qab] hello", "qab")]
    assert synthesizer.warmed_languages == ["qab"]
    assert wav.name == "synthetic-qab.wav"
