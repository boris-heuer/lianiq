"""CAP-0177 WI-02: ``UsageMode.meeting`` and requirement row 8 (meeting contract.md §6).

Rows 1-7 stay covered, unchanged, by ``test_requirements.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from synthetic import provisioned_catalog

from lianiq.languages import (
    BUILTIN_REGISTRY,
    CALL_BRIDGE_MODE,
    MEETING_MODE,
    DeviceReadiness,
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
from lianiq.languages.requirements import (
    CALL_ENDPOINT_ROLES,
    MEETING_ENDPOINT_ROLES,
    meeting_local_speech_requirements,
    ordered_requirements,
)

DE = LanguageId("de")
ZH = LanguageId("zh-Hans")
MEETING_ROLES = frozenset(MEETING_ENDPOINT_ROLES)
ALL_OTHER_DEVICES = DeviceReadiness(
    microphone=True, playback=True, call_endpoints=frozenset(CALL_ENDPOINT_ROLES)
)


def stt(language: str) -> Requirement:
    return Requirement(RequirementKind.RECOGNITION, language)


def mt(key: str) -> Requirement:
    return Requirement(RequirementKind.TRANSLATION, key)


def voice(language: str) -> Requirement:
    return Requirement(RequirementKind.VOICE, language)


def meeting(local: str = "de") -> SessionPair:
    return SessionPair(
        BUILTIN_REGISTRY.pair("de", "zh-Hans"), MEETING_MODE, local_language=LanguageId(local)
    )


def endpoint(role: str) -> Requirement:
    return Requirement(RequirementKind.MEETING_ENDPOINTS, role)


def row8_catalog(root: Path, voices: tuple[str, ...] = ("zh-Hans",)):
    return provisioned_catalog(
        root,
        BUILTIN_REGISTRY,
        recognition=["de", "zh-Hans"],
        edges=["de>zh-Hans", "zh-Hans>de"],
        voices=voices,
    )


def test_meeting_mode_is_microphone_bidirectional_spoken_and_not_call_bridge() -> None:
    assert MEETING_MODE == UsageMode(
        InputKind.MICROPHONE, RoutingKind.BIDIRECTIONAL, OutputKind.SPOKEN, meeting=True
    )
    assert MEETING_MODE.call_bridge is False
    plain = UsageMode(InputKind.MICROPHONE, RoutingKind.BIDIRECTIONAL, OutputKind.SPOKEN)
    assert plain.meeting is False
    with pytest.raises(UnsupportedModeError):
        UsageMode(InputKind.MICROPHONE, RoutingKind.BIDIRECTIONAL, OutputKind.TEXT, meeting=True)
    with pytest.raises(UnsupportedModeError):
        UsageMode(InputKind.TYPED, RoutingKind.FIXED, OutputKind.SPOKEN, meeting=True)
    with pytest.raises(UnsupportedModeError):
        UsageMode(
            InputKind.MICROPHONE,
            RoutingKind.BIDIRECTIONAL,
            OutputKind.SPOKEN,
            call_bridge=True,
            meeting=True,
        )


def test_ac01_meeting_session_pair_requires_a_local_language_from_the_pair() -> None:
    pair = BUILTIN_REGISTRY.pair("de", "zh-Hans")

    session = meeting()

    assert session.local_language == DE
    assert session.pair.other(session.local_language) == ZH
    assert session.fixed_source is None
    with pytest.raises(UnsupportedModeError):
        SessionPair(pair, MEETING_MODE)
    with pytest.raises(UnsupportedModeError):
        SessionPair(pair, MEETING_MODE, local_language=LanguageId("en"))


@pytest.mark.parametrize(
    ("local", "table"), [("de", "zh-Hans"), ("zh-Hans", "de")], ids=["local-de", "local-zh"]
)
def test_requirement_table_row8_meeting(local: str, table: str) -> None:
    expected = (
        stt("de"),
        stt("zh-Hans"),
        mt("de>zh-Hans"),
        mt("zh-Hans>de"),
        voice(table),
        endpoint("table_capture"),
        endpoint("table_render"),
        endpoint("user_capture"),
    )

    assert MEETING_ENDPOINT_ROLES == ("table_capture", "table_render", "user_capture")
    assert ordered_requirements(meeting(local)) == expected
    assert requirements(meeting(local)) == frozenset(expected)
    assert voice(local) not in requirements(meeting(local))


def test_ac02_row8_is_available_with_models_and_the_three_endpoints(tmp_path: Path) -> None:
    devices = DeviceReadiness(meeting_endpoints=MEETING_ROLES)

    result = check(meeting(), row8_catalog(tmp_path), devices)

    assert result == check(meeting(), row8_catalog(tmp_path), devices)
    assert result.available is True
    assert result.missing == ()


def test_ac02_row8_lists_each_missing_item_in_order(tmp_path: Path) -> None:
    catalog = provisioned_catalog(tmp_path, BUILTIN_REGISTRY, recognition=["de"], voices=["de"])
    devices = DeviceReadiness(
        microphone=True,
        playback=True,
        call_endpoints=frozenset(CALL_ENDPOINT_ROLES),
        meeting_endpoints=frozenset({"user_capture"}),
    )

    result = check(meeting(), catalog, devices)

    assert result.available is False
    assert result.missing == (
        stt("zh-Hans"),
        mt("de>zh-Hans"),
        mt("zh-Hans>de"),
        voice("zh-Hans"),
        endpoint("table_capture"),
        endpoint("table_render"),
    )
    assert [describe(item, BUILTIN_REGISTRY) for item in result.missing] == [
        "speech recognition Mandarin (Simplified)",
        "translation German → Mandarin (Simplified)",
        "translation Mandarin (Simplified) → German",
        "voice Mandarin (Simplified)",
        "table microphone",
        "table speaker",
    ]


def test_ac03_a_conflicting_user_capture_removed_from_readiness_blocks_row8(
    tmp_path: Path,
) -> None:
    # The page drops a role in conflict (USER_IS_TABLE -> user_capture) from the readiness.
    devices = DeviceReadiness(meeting_endpoints=MEETING_ROLES - {"user_capture"})

    result = check(meeting(), row8_catalog(tmp_path), devices)

    assert result.available is False
    assert result.missing == (endpoint("user_capture"),)
    assert describe(result.missing[0], BUILTIN_REGISTRY) == "your microphone"


def test_row8_ignores_the_local_voice_and_the_conversation_devices(tmp_path: Path) -> None:
    devices = DeviceReadiness(meeting_endpoints=MEETING_ROLES)

    result = check(meeting(), row8_catalog(tmp_path, voices=("zh-Hans",)), devices)

    assert result.available is True
    assert Requirement(RequirementKind.MICROPHONE) not in requirements(meeting())
    assert Requirement(RequirementKind.PLAYBACK) not in requirements(meeting())


def test_meeting_local_speech_requirements_gate_only_the_speech_switch(tmp_path: Path) -> None:
    session = meeting()
    speech = meeting_local_speech_requirements(session)
    catalog = row8_catalog(tmp_path)

    assert speech == (voice("de"), endpoint("local_render"))
    assert not set(speech) & requirements(session)
    assert check(session, catalog, DeviceReadiness(meeting_endpoints=MEETING_ROLES)).available
    assert describe(speech[1], BUILTIN_REGISTRY, local_language=DE) == "output for German speech"
    with pytest.raises(ValueError, match="local_language"):
        describe(speech[1], BUILTIN_REGISTRY)
    with pytest.raises(UnsupportedModeError):
        meeting_local_speech_requirements(
            SessionPair(
                BUILTIN_REGISTRY.pair("de", "zh-Hans"),
                UsageMode(InputKind.MICROPHONE, RoutingKind.BIDIRECTIONAL, OutputKind.SPOKEN),
            )
        )


def test_meeting_endpoint_readiness_is_separate_from_call_endpoints(tmp_path: Path) -> None:
    call = SessionPair(BUILTIN_REGISTRY.pair("de", "zh-Hans"), CALL_BRIDGE_MODE, local_language=DE)
    only_meeting = DeviceReadiness(meeting_endpoints=MEETING_ROLES)
    catalog = provisioned_catalog(
        tmp_path,
        BUILTIN_REGISTRY,
        recognition=["de", "zh-Hans"],
        edges=["de>zh-Hans", "zh-Hans>de"],
        voices=["de", "zh-Hans"],
    )

    assert DeviceReadiness().meeting_endpoints == frozenset()
    assert check(call, catalog, only_meeting).missing == tuple(
        Requirement(RequirementKind.CALL_ENDPOINTS, role) for role in CALL_ENDPOINT_ROLES
    )
    assert check(meeting(), catalog, ALL_OTHER_DEVICES).missing == tuple(
        endpoint(role) for role in MEETING_ENDPOINT_ROLES
    )
