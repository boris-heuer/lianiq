"""CAP-0172 contract §5: Translate and Play readiness (AC-06, AC-08, AC-09, AC-28 unit halves)."""

from __future__ import annotations

from pathlib import Path

import pytest

from lianiq.languages import (
    CapabilityCatalog,
    DirectedEdge,
    LanguageId,
    ReadinessProbe,
    RequirementKind,
    describe,
)
from lianiq.text_translation.readiness import (
    SPOKEN_TEXT_MODE,
    TEXT_MODE,
    PlayBlock,
    TranslateBlock,
    text_readiness,
    text_session,
)
from tests.languages.synthetic import QAA, provisioned_catalog
from tests.text_translation._text_helpers import (
    DE,
    ZH,
    FakePacks,
    Speakers,
    three_language_registry,
)

READY = Speakers(True)


class RecordingCatalog:
    """Forwards to a catalog and records which capability kinds are read."""

    def __init__(self, catalog: CapabilityCatalog) -> None:
        self._catalog = catalog
        self.reads: list[str] = []

    def __getattr__(self, name: str):
        self.reads.append(name)
        return getattr(self._catalog, name)


@pytest.fixture
def registry():
    return three_language_registry()


def test_text_sessions_use_typed_fixed_routing(registry) -> None:
    session = text_session(DE, ZH, spoken=False)
    assert session.mode == TEXT_MODE and session.fixed_source == DE and session.fixed_target == ZH
    assert text_session(ZH, DE, spoken=True).mode == SPOKEN_TEXT_MODE


def test_ac06_synthetic_direction_works_and_an_unconfigured_one_is_unsupported(
    tmp_path: Path, registry
) -> None:
    catalog = provisioned_catalog(tmp_path, registry, edges=["de>qaa", "qaa>de"])
    ready = text_readiness(DE, QAA, catalog, None, READY)
    assert ready.translate is TranslateBlock.NONE
    unsupported = text_readiness(ZH, QAA, catalog, FakePacks(), READY)
    assert unsupported.translate is TranslateBlock.UNSUPPORTED
    assert (
        describe(unsupported.missing[0], registry)
        == "translation Mandarin (Simplified) → Synthetic A"
    )


def test_ac08_a_catalog_pack_that_is_not_installed_is_pack_missing(
    tmp_path: Path, registry
) -> None:
    catalog = provisioned_catalog(tmp_path, registry, voices=["zh-Hans"])
    readiness = text_readiness(DE, ZH, catalog, FakePacks(frozenset({"de>zh-Hans"})), READY)
    assert readiness.translate is TranslateBlock.PACK_MISSING
    assert [describe(r, registry) for r in readiness.missing] == [
        "translation German → Mandarin (Simplified)"
    ]


def test_a_configured_edge_with_missing_files_is_pack_missing(tmp_path: Path, registry) -> None:
    catalog = CapabilityCatalog(
        registry, ReadinessProbe(tmp_path), translation={DirectedEdge(DE, ZH): Path("models/none")}
    )
    assert text_readiness(DE, ZH, catalog, None, READY).translate is TranslateBlock.PACK_MISSING


def test_ac09_no_edge_and_no_catalog_pack_is_unsupported(tmp_path: Path, registry) -> None:
    catalog = provisioned_catalog(tmp_path, registry, edges=["zh-Hans>de"])
    assert (
        text_readiness(DE, ZH, catalog, FakePacks(), READY).translate is TranslateBlock.UNSUPPORTED
    )
    assert text_readiness(DE, ZH, catalog, None, READY).translate is TranslateBlock.UNSUPPORTED
    assert text_readiness(ZH, DE, catalog, None, READY).translate is TranslateBlock.NONE


def test_ac28_a_missing_target_voice_blocks_only_play(tmp_path: Path, registry) -> None:
    catalog = provisioned_catalog(tmp_path, registry, edges=["de>zh-Hans"], voices=["de"])
    readiness = text_readiness(DE, ZH, catalog, None, READY)
    assert (readiness.translate, readiness.play) == (TranslateBlock.NONE, PlayBlock.VOICE_MISSING)
    assert [describe(r, registry) for r in readiness.missing] == ["voice Mandarin (Simplified)"]


def test_play_needs_the_conversation_output_device(tmp_path: Path, registry) -> None:
    catalog = provisioned_catalog(tmp_path, registry, edges=["de>zh-Hans"], voices=["zh-Hans"])
    assert text_readiness(DE, ZH, catalog, None, READY).play is PlayBlock.NONE
    silent = text_readiness(DE, ZH, catalog, None, Speakers(False))
    assert silent.play is PlayBlock.SPEAKERS_MISSING
    assert [r.kind for r in silent.missing] == [RequirementKind.PLAYBACK]
    both = text_readiness(
        DE, ZH, provisioned_catalog(tmp_path / "x", registry), None, Speakers(False)
    )
    assert both.play is PlayBlock.VOICE_MISSING
    assert [r.kind for r in both.missing] == [
        RequirementKind.TRANSLATION,
        RequirementKind.VOICE,
        RequirementKind.PLAYBACK,
    ]


def test_recognition_and_the_microphone_are_never_read(tmp_path: Path, registry) -> None:
    catalog = RecordingCatalog(provisioned_catalog(tmp_path, registry, recognition=["de"]))
    text_readiness(DE, ZH, catalog, None, READY)  # type: ignore[arg-type]
    assert "recognition" not in catalog.reads
    assert set(catalog.reads) <= {"translation", "voice"}


def test_unknown_language_is_rejected(tmp_path: Path, registry) -> None:
    catalog = provisioned_catalog(tmp_path, registry)
    with pytest.raises(LookupError):
        text_readiness(DE, LanguageId("qzz"), catalog, None, READY)
