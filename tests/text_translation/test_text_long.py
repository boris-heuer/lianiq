"""CAP-0172 rev 1.1 (lianiq#35): long text in bounded segments with progress (AC-39, AC-40)."""

from __future__ import annotations

from lianiq.text_translation.jobs import TranslationJobs
from lianiq.text_translation.limits import MAX_SOURCE_CODE_POINTS, SourceCheck, check_source
from lianiq.text_translation.segments import SEGMENT_TOKEN_BUDGET, split_source
from lianiq.text_translation.state import DraftState
from tests.text_translation._text_helpers import (
    DE,
    ZH,
    GatedSpy,
    GuiThread,
    IdentitySpy,
    fake_tokens,
)


def long_text() -> str:
    paragraph = " ".join(f"Satz {i} hat einige Wörter." for i in range(40))
    text = "\n\n".join(paragraph for _ in range(60))
    return text[: MAX_SOURCE_CODE_POINTS - 1].rstrip() + "."


def test_ac39_a_text_at_the_limit_is_allowed_and_split_within_the_budget() -> None:
    text = long_text()
    assert len(text) <= MAX_SOURCE_CODE_POINTS and check_source(text) is SourceCheck.OK
    segments = [s for line in split_source(text, fake_tokens) for s in line]
    assert len(segments) > 1_000
    assert max(fake_tokens(s.text) for s in segments) <= SEGMENT_TOKEN_BUDGET


def test_ac40_progress_is_posted_per_segment_in_order_and_the_result_is_complete() -> None:
    gui, spy = GuiThread(), IdentitySpy()
    jobs = TranslationJobs(lambda: spy, gui.post)
    draft = DraftState(DE, ZH, "Eins. Zwei. Drei.\n\nVier.")
    seen: list[tuple[int, int, int]] = []
    done: list[int] = []
    request = draft.request()
    jobs.start(request, lambda r: done.append(r.result_id), None, None, lambda *p: seen.append(p))
    gui.pump(lambda: done)
    jobs.shutdown()
    rid = request.request_id
    assert seen == [(rid, n, 4) for n in range(5)]


def test_ac40_cancel_stops_progress_at_the_next_segment() -> None:
    gui, spy = GuiThread(), GatedSpy()
    jobs = TranslationJobs(lambda: spy, gui.post)
    draft = DraftState(DE, ZH, "Eins. Zwei. Drei.")
    seen: list[tuple[int, int, int]] = []
    cancelled: list[int] = []
    request = draft.request()
    jobs.start(request, None, None, cancelled.append, lambda *p: seen.append(p))
    spy.wait_entered()
    jobs.cancel()
    spy.gate.set()
    gui.pump(lambda: cancelled)
    jobs.shutdown()
    assert cancelled == [request.request_id]
    assert seen == [(request.request_id, 0, 3)] and len(spy.calls) == 1
