from __future__ import annotations

import pytest
from synthetic import QAA, QAB, synthetic_registry

from lianiq.languages import (
    BUILTIN_REGISTRY,
    Availability,
    LanguageDefinition,
    LanguageId,
    LanguagePair,
    LanguageRegistry,
    PlannedLanguageError,
    SameLanguagePairError,
    UnknownLanguageError,
    normalize_language_id,
)


def test_ac01_builtin_registry_lists_qualified_and_planned_languages() -> None:
    languages = BUILTIN_REGISTRY.languages()

    assert [(item.id, item.availability) for item in languages] == [
        ("de", Availability.QUALIFIED),
        ("zh-Hans", Availability.QUALIFIED),
        ("en", Availability.PLANNED),
        ("es", Availability.PLANNED),
        ("fr", Availability.PLANNED),
    ]
    for item in languages:
        # The stable ID is its own field: never an English name, native name or engine code
        # set, and at least one engine needs a code that differs from the ID.
        assert item.id not in (item.english_name, item.native_name)
        assert item.engine_codes
        assert set(item.engine_codes.values()) != {item.id}
    assert BUILTIN_REGISTRY.get("zh-Hans").english_name == "Mandarin (Simplified)"
    assert BUILTIN_REGISTRY.get("zh-Hans").native_name == "普通话（简体）"
    assert dict(BUILTIN_REGISTRY.get("zh-Hans").engine_codes) == {
        "whisper": "zh",
        "piper": "zh_CN",
        "sherpa-onnx": "zh",
    }


def test_engine_codes_map_back_to_language_ids() -> None:
    assert BUILTIN_REGISTRY.from_engine_code("whisper", "zh") == "zh-Hans"
    assert BUILTIN_REGISTRY.from_engine_code("piper", "de_DE") == "de"
    assert BUILTIN_REGISTRY.from_engine_code("whisper", "xx") is None
    assert BUILTIN_REGISTRY.from_engine_code("unknown-engine", "de") is None


def test_ids_are_case_normalised_and_unknown_ids_raise() -> None:
    assert normalize_language_id("ZH-hans") == "zh-Hans"
    assert normalize_language_id("de_de") == "de-DE"
    assert BUILTIN_REGISTRY.get("DE").id == "de"
    assert BUILTIN_REGISTRY.display_name("zh-hans") == "Mandarin (Simplified)"
    with pytest.raises(UnknownLanguageError):
        BUILTIN_REGISTRY.get("zh")
    with pytest.raises(UnknownLanguageError):
        BUILTIN_REGISTRY.get("")


def test_pair_rejects_same_planned_and_unknown_members() -> None:
    with pytest.raises(SameLanguagePairError):
        BUILTIN_REGISTRY.pair("de", "de")
    with pytest.raises(SameLanguagePairError):
        BUILTIN_REGISTRY.pair("zh-Hans", "ZH-HANS")
    with pytest.raises(PlannedLanguageError):
        BUILTIN_REGISTRY.pair("de", "en")
    with pytest.raises(UnknownLanguageError):
        BUILTIN_REGISTRY.pair("de", "qaa")


def test_pair_members_follow_registry_order_and_other_stays_within_the_pair() -> None:
    pair = BUILTIN_REGISTRY.pair("zh-Hans", "de")

    assert pair == LanguagePair(LanguageId("de"), LanguageId("zh-Hans"))
    assert pair.members == ("de", "zh-Hans")
    assert pair.other(LanguageId("de")) == "zh-Hans"
    assert pair.other(LanguageId("zh-Hans")) == "de"
    with pytest.raises(ValueError):
        pair.other(LanguageId("en"))
    with pytest.raises(SameLanguagePairError):
        LanguagePair(LanguageId("de"), LanguageId("de"))


def test_synthetic_registry_builds_a_third_language_pair() -> None:
    registry = synthetic_registry()

    assert registry.pair(QAB, QAA).members == (QAA, QAB)
    assert registry.display_name(QAA) == "Synthetic A"
    with pytest.raises(UnknownLanguageError):
        registry.get("de")


def test_registry_rejects_duplicate_ids_and_definitions_are_immutable() -> None:
    definition = LanguageDefinition(
        LanguageId("qaa"), "Synthetic A", "A", {"whisper": "xa"}, Availability.QUALIFIED
    )
    with pytest.raises(ValueError):
        LanguageRegistry([definition, definition])
    with pytest.raises(TypeError):
        definition.engine_codes["whisper"] = "changed"  # type: ignore[index]
