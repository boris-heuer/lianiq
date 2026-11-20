"""CAP-0171 AC-23: ``language_rows`` derives planned and unsupported rows from the registry."""

from __future__ import annotations

from pathlib import Path

import pytest
from _pack_fixtures import load_catalog, mt_entry, voice_entry

from lianiq.languages import (
    BUILTIN_REGISTRY,
    Availability,
    DirectedEdge,
    LanguageDefinition,
    LanguageId,
    LanguageRegistry,
)
from lianiq.packs.catalog import BUILTIN_CATALOG_PATH, PackCatalog, PackKind
from lianiq.packs.state import LanguageRow, PackState, language_rows

DE = LanguageId("de")
ZH = LanguageId("zh-Hans")
EN = LanguageId("en")
QAA = LanguageId("qaa")
QAB = LanguageId("qab")


def synthetic_registry() -> LanguageRegistry:
    return LanguageRegistry(
        LanguageDefinition(tag, tag, tag, {}, Availability.QUALIFIED) for tag in (QAA, QAB)
    )


@pytest.fixture(scope="module")
def builtin_rows() -> tuple[LanguageRow, ...]:
    return language_rows(BUILTIN_REGISTRY, PackCatalog.load(BUILTIN_CATALOG_PATH, BUILTIN_REGISTRY))


def _row(rows: tuple[LanguageRow, ...], kind: PackKind, subject: object) -> LanguageRow:
    (row,) = [row for row in rows if row.kind is kind and row.subject == subject]
    return row


def test_builtin_rows_map_qualified_capabilities_to_their_packs(
    builtin_rows: tuple[LanguageRow, ...],
) -> None:
    assert _row(builtin_rows, PackKind.RECOGNITION, DE).pack_id == "stt-faster-whisper-small"
    assert _row(builtin_rows, PackKind.RECOGNITION, ZH).pack_id == "stt-faster-whisper-small"
    assert _row(builtin_rows, PackKind.TRANSLATION, DirectedEdge(DE, ZH)).pack_id == (
        "mt-de-zh-hans"
    )
    assert _row(builtin_rows, PackKind.TRANSLATION, DirectedEdge(ZH, DE)).pack_id == (
        "mt-zh-hans-de"
    )
    assert _row(builtin_rows, PackKind.VOICE, ZH).pack_id == "tts-zh-hans-aishell3"
    pack_rows = [row for row in builtin_rows if row.pack_id is not None]
    assert len(pack_rows) == 6  # the six capabilities of the five packs
    assert all(row.state is PackState.DOWNLOADABLE for row in pack_rows)


def test_planned_languages_and_their_edges_are_planned(
    builtin_rows: tuple[LanguageRow, ...],
) -> None:
    planned = [
        definition.id
        for definition in BUILTIN_REGISTRY.languages()
        if definition.availability.value == "planned"
    ]
    assert EN in planned
    for language in planned:
        for kind in (PackKind.RECOGNITION, PackKind.VOICE):
            row = _row(builtin_rows, kind, language)
            assert (row.state, row.pack_id) == (PackState.PLANNED, None)
        row = _row(builtin_rows, PackKind.TRANSLATION, DirectedEdge(DE, language))
        assert (row.state, row.pack_id) == (PackState.PLANNED, None)
    assert not [row for row in builtin_rows if row.state is PackState.UNSUPPORTED]


def test_rows_follow_registry_order_grouped_by_kind(
    builtin_rows: tuple[LanguageRow, ...],
) -> None:
    ids = [definition.id for definition in BUILTIN_REGISTRY.languages()]
    kinds = [row.kind for row in builtin_rows]
    assert kinds == sorted(kinds, key=list(PackKind).index)
    assert [r.subject for r in builtin_rows if r.kind is PackKind.RECOGNITION] == ids
    assert [r.subject for r in builtin_rows if r.kind is PackKind.VOICE] == ids
    edges = [r.subject for r in builtin_rows if r.kind is PackKind.TRANSLATION]
    assert edges == [DirectedEdge(a, b) for a in ids for b in ids if a != b]


def test_qualified_capabilities_without_a_pack_are_unsupported(tmp_path: Path) -> None:
    registry = synthetic_registry()
    empty = load_catalog(tmp_path, name="empty.json")
    rows = language_rows(registry, PackCatalog.load(tmp_path / "empty.json", registry))

    assert rows == (
        LanguageRow(QAA, PackKind.RECOGNITION, PackState.UNSUPPORTED, None),
        LanguageRow(QAB, PackKind.RECOGNITION, PackState.UNSUPPORTED, None),
        LanguageRow(DirectedEdge(QAA, QAB), PackKind.TRANSLATION, PackState.UNSUPPORTED, None),
        LanguageRow(DirectedEdge(QAB, QAA), PackKind.TRANSLATION, PackState.UNSUPPORTED, None),
        LanguageRow(QAA, PackKind.VOICE, PackState.UNSUPPORTED, None),
        LanguageRow(QAB, PackKind.VOICE, PackState.UNSUPPORTED, None),
    )
    assert empty.packs() == ()


def test_a_partial_catalog_leaves_the_reverse_edge_unsupported(tmp_path: Path) -> None:
    rows = language_rows(BUILTIN_REGISTRY, load_catalog(tmp_path, mt_entry(), voice_entry()))

    assert _row(rows, PackKind.TRANSLATION, DirectedEdge(DE, ZH)).pack_id == "mt-a"
    reverse = _row(rows, PackKind.TRANSLATION, DirectedEdge(ZH, DE))
    assert (reverse.state, reverse.pack_id) == (PackState.UNSUPPORTED, None)
    assert _row(rows, PackKind.VOICE, DE).pack_id == "tts-a"
    assert _row(rows, PackKind.VOICE, ZH).state is PackState.UNSUPPORTED
    assert _row(rows, PackKind.RECOGNITION, DE).state is PackState.UNSUPPORTED
