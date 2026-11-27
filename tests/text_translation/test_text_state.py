"""CAP-0172 contract §3: draft revisions, requests and the stale and late-result rules."""

from __future__ import annotations

import pytest

from lianiq.languages import DirectedEdge
from lianiq.text_translation.state import DraftState, ResultState, TextResult
from tests.text_translation._text_helpers import DE, DE_ZH, ZH


def result_for(request, text: str = "译文") -> TextResult:
    return TextResult(request.request_id, request.revision, request.edge, text, (text,))


def shown(draft: DraftState) -> DraftState:
    request = draft.request()
    assert draft.accept(result_for(request))
    assert draft.result_state is ResultState.CURRENT
    return draft


def test_requests_bind_revision_edge_and_text() -> None:
    draft = DraftState(DE, ZH)
    assert draft.result_state is ResultState.NONE
    draft.edit("Hallo")
    first, second = draft.request(), draft.request()
    assert (first.request_id, second.request_id) == (1, 2)
    assert (first.revision, first.edge, first.text) == (1, DE_ZH, "Hallo")
    assert draft.latest_request == 2
    assert "Hallo" not in repr(first) and "Hallo" not in repr(result_for(first, "Hallo"))


@pytest.mark.parametrize("text", ["", "   ", "x" * 50_001])
def test_ac11_ac12_no_request_unless_the_source_is_ok(text: str) -> None:
    draft = DraftState(DE, ZH, text)
    with pytest.raises(ValueError):
        draft.request()
    assert draft.latest_request is None
    assert draft.text == text  # the draft is unchanged


def test_ac03_swap_exchanges_languages_keeps_the_draft_and_stales_the_result() -> None:
    draft = shown(DraftState(DE, ZH, "Guten Tag."))
    draft.swap()
    assert (draft.source, draft.target, draft.text) == (ZH, DE, "Guten Tag.")
    assert draft.result_state is ResultState.STALE
    assert draft.request().edge == DirectedEdge(ZH, DE)


@pytest.mark.parametrize(
    "change",
    [
        lambda draft: draft.edit("Guten Abend."),
        lambda draft: draft.edit(""),
        lambda draft: draft.set_languages(ZH, DE),
        lambda draft: draft.swap(),
    ],
)
def test_ac16_any_edit_or_language_change_stales_the_result_at_once(change) -> None:
    draft = shown(DraftState(DE, ZH, "Guten Tag."))
    assert draft.current_result() is not None
    change(draft)
    assert draft.result_state is ResultState.STALE
    assert draft.current_result() is None  # no Copy translation, Play or Replay


def test_ac17_a_late_result_never_replaces_a_newer_one() -> None:
    draft = DraftState(DE, ZH, "A")
    request_a = draft.request()
    draft.edit("B")
    request_b = draft.request()
    assert draft.accept(result_for(request_b, "B'"))
    assert not draft.accept(result_for(request_a, "A'"))
    assert draft.result is not None and draft.result.text == "B'"
    assert draft.result_state is ResultState.CURRENT


def test_ac17_a_result_after_an_edit_without_new_request_is_discarded() -> None:
    draft = shown(DraftState(DE, ZH, "A"))
    old = draft.result
    request = draft.request()
    draft.edit("A2")
    assert not draft.accept(result_for(request, "late"))
    assert draft.result is old
    assert draft.result_state is ResultState.STALE


def test_ac04_typing_pasting_and_clearing_make_no_request() -> None:
    draft = DraftState(DE, ZH)
    for text in ("H", "Ha", "Hallo Welt, ein eingefügter Absatz.\nZweite Zeile.", ""):
        draft.edit(text)
    assert draft.latest_request is None
    assert draft.revision == 4
