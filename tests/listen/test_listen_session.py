"""CAP-0170 contract §2: listen session and Start readiness (AC-03, AC-04, AC-22 unit halves)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from lianiq.languages import describe
from lianiq.listen.session import LISTEN_MODE, StartBlock, listen_readiness, listen_session
from lianiq.ui.shell.workspaces import WorkspaceId
from tests.languages.synthetic import provisioned_catalog
from tests.text_translation._text_helpers import DE, ZH, FakePacks, three_language_registry


@dataclass(frozen=True)
class Mic:
    ready: bool


class RecordingCatalog:
    def __init__(self, catalog) -> None:
        self._catalog = catalog
        self.reads: list[str] = []

    def __getattr__(self, name: str):
        self.reads.append(name)
        return getattr(self._catalog, name)


@pytest.fixture
def registry():
    return three_language_registry()


def session(source=DE, target=ZH):
    return listen_session(three_language_registry().pair(source, target), source)


def test_listen_session_is_row_3_with_the_fixed_source() -> None:
    built = session()
    assert built.mode == LISTEN_MODE and built.fixed_source == DE and built.fixed_target == ZH


def test_ready_direction_reads_only_recognition_and_translation(tmp_path: Path, registry) -> None:
    catalog = RecordingCatalog(
        provisioned_catalog(tmp_path, registry, recognition=["de"], edges=["de>zh-Hans"])
    )
    readiness = listen_readiness(session(), catalog, None, Mic(True), None)
    assert (readiness.block, readiness.missing) == (StartBlock.NONE, ())
    assert set(catalog.reads) <= {"recognition", "translation"}


def test_ac03_missing_translation_with_a_pack_is_pack_missing(tmp_path: Path, registry) -> None:
    catalog = provisioned_catalog(tmp_path, registry, recognition=["de"])
    packs = FakePacks(frozenset({"de>zh-Hans"}))
    readiness = listen_readiness(session(), catalog, packs, Mic(True), None)
    assert readiness.block is StartBlock.PACK_MISSING
    assert [describe(r, registry) for r in readiness.missing] == [
        "translation German → Mandarin (Simplified)"
    ]


def test_ac04_an_unconfigured_direction_without_a_pack_is_unsupported(
    tmp_path: Path, registry
) -> None:
    catalog = provisioned_catalog(tmp_path, registry, recognition=["de"], edges=["zh-Hans>de"])
    with_packs = listen_readiness(session(), catalog, FakePacks(), Mic(True), None)
    without_packs = listen_readiness(session(), catalog, None, Mic(False), None)
    assert with_packs.block is StartBlock.UNSUPPORTED
    assert without_packs.block is StartBlock.UNSUPPORTED


def test_microphone_then_busy_follow_the_model_blocks(tmp_path: Path, registry) -> None:
    catalog = provisioned_catalog(tmp_path, registry, recognition=["de"], edges=["de>zh-Hans"])
    no_mic = listen_readiness(session(), catalog, None, Mic(False), WorkspaceId.CONVERSATION)
    assert no_mic.block is StartBlock.MICROPHONE_MISSING
    busy = listen_readiness(session(), catalog, None, Mic(True), WorkspaceId.CONVERSATION)
    assert (busy.block, busy.missing) == (StartBlock.BUSY, ())
