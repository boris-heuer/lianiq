"""CAP-0172 contract §6: the translation worker (AC-04, AC-13, AC-14, AC-15, AC-17, AC-18)."""

from __future__ import annotations

import logging
import threading

import pytest

from lianiq.languages import CapabilityMissingError, Requirement, RequirementKind
from lianiq.text_translation.jobs import FailureReason, TranslationJobs, failure_reason
from lianiq.text_translation.segments import SEGMENT_TOKEN_BUDGET
from lianiq.text_translation.state import DraftState, ResultState
from tests.text_translation._text_helpers import (
    DE,
    ZH,
    GatedSpy,
    GuiThread,
    IdentitySpy,
    MeasuredSpy,
    fake_tokens,
)

SECRET = "Geheimer Satz für das Protokoll."


class Outcomes:
    def __init__(self, draft: DraftState) -> None:
        self.draft = draft
        self.done: list[int] = []
        self.failed: list[tuple[int, FailureReason]] = []
        self.cancelled: list[int] = []

    def start(self, jobs: TranslationJobs):
        request = self.draft.request()
        jobs.start(
            request, self._done, lambda i, r: self.failed.append((i, r)), self.cancelled.append
        )
        return request

    def _done(self, result) -> None:
        self.done.append(result.result_id)
        self.draft.accept(result)

    def settled(self, *ids: int):
        return lambda: all(
            i in self.done + self.cancelled + [f[0] for f in self.failed] for i in ids
        )


@pytest.fixture
def gui():
    return GuiThread()


def run(spy, text: str, gui: GuiThread, source=DE, target=ZH) -> DraftState:
    jobs = TranslationJobs(lambda: spy, gui.post)
    outcomes = Outcomes(DraftState(source, target, text))
    request = outcomes.start(jobs)
    gui.pump(outcomes.settled(request.request_id))
    jobs.shutdown()
    assert outcomes.done == [request.request_id]
    return outcomes.draft


def test_ac04_ac15_one_request_one_job_with_empty_context(gui) -> None:
    spy = IdentitySpy()
    draft = run(spy, "Erster Satz. Zweiter Satz.", gui)
    assert spy.calls == [("Erster Satz.", "de>zh-Hans", ()), ("Zweiter Satz.", "de>zh-Hans", ())]
    assert draft.result is not None and draft.result.segments == ("Erster Satz.", "Zweiter Satz.")
    assert draft.result_state is ResultState.CURRENT


def test_ac13_token_count_drives_the_budget_and_layout_survives(gui) -> None:
    long = " ".join(f"wort{i}" for i in range(200)) + "."
    text = f"{long}\n\n  Kurz.\n你好。再见。"
    spy = MeasuredSpy()
    draft = run(spy, text, gui)
    assert max(fake_tokens(call[0]) for call in spy.calls) <= SEGMENT_TOKEN_BUDGET
    assert len(spy.calls) > 4
    assert draft.result is not None and draft.result.text == text


def test_ac14_cjk_and_rtl_code_points_round_trip(gui) -> None:
    text = "中文段落。第二句！\n\nمرحبا بالعالم؟ هذا نص.\n\u05e9\u05dc\u05d5\u05dd."
    draft = run(IdentitySpy(), text, gui, source=ZH, target=DE)
    assert draft.result is not None and draft.result.text == text


def test_ac17_gated_request_a_is_superseded_by_b(gui) -> None:
    spy = GatedSpy()
    jobs = TranslationJobs(lambda: spy, gui.post)
    outcomes = Outcomes(DraftState(DE, ZH, "Satz A eins. Satz A zwei."))
    a = outcomes.start(jobs)
    spy.wait_entered()
    outcomes.draft.edit("Satz B.")
    b = outcomes.start(jobs)
    spy.gate.set()
    gui.pump(outcomes.settled(a.request_id, b.request_id))
    jobs.shutdown()
    assert outcomes.cancelled == [a.request_id] and outcomes.done == [b.request_id]
    assert [call[0] for call in spy.calls] == [
        "Satz A eins.",
        "Satz B.",
    ]  # A stopped at the boundary
    assert outcomes.draft.result is not None and outcomes.draft.result.result_id == b.request_id


def test_cancel_takes_effect_at_the_next_segment(gui) -> None:
    spy = GatedSpy()
    jobs = TranslationJobs(lambda: spy, gui.post)
    outcomes = Outcomes(DraftState(DE, ZH, "Eins. Zwei. Drei."))
    request = outcomes.start(jobs)
    spy.wait_entered()
    jobs.cancel()
    spy.gate.set()
    gui.pump(outcomes.settled(request.request_id))
    jobs.shutdown()
    assert outcomes.cancelled == [request.request_id] and len(spy.calls) == 1
    assert outcomes.draft.result is None  # partial output is never shown


def test_ac18_fifty_edits_with_interleaved_translate(gui) -> None:
    spy = IdentitySpy(delay=0.002)
    jobs = TranslationJobs(lambda: spy, gui.post)
    outcomes = Outcomes(DraftState(DE, ZH))
    requests = []
    for i in range(50):
        outcomes.draft.edit(f"Satz {i} eins. Satz {i} zwei. Satz {i} drei. Satz {i} vier.")
        if i % 2:
            requests.append(outcomes.start(jobs))
    gui.pump(outcomes.settled(*(r.request_id for r in requests)), timeout=10)
    jobs.shutdown()
    assert spy.overlap == 1
    assert outcomes.done[-1] == requests[-1].request_id
    assert len(spy.calls) < 4 * len(requests)  # earlier jobs stopped early
    assert outcomes.draft.result is not None
    assert outcomes.draft.result.result_id == requests[-1].request_id
    assert outcomes.draft.result_state is ResultState.CURRENT


def test_the_translator_is_fetched_per_job(gui) -> None:
    spies = [IdentitySpy(), IdentitySpy()]
    jobs = TranslationJobs(lambda: spies[0] if not spies[0].calls else spies[1], gui.post)
    outcomes = Outcomes(DraftState(DE, ZH, "Satz."))
    first, second = outcomes.start(jobs), None
    gui.pump(outcomes.settled(first.request_id))
    second = outcomes.start(jobs)
    gui.pump(outcomes.settled(second.request_id))
    jobs.shutdown()
    assert len(spies[0].calls) == 1 and len(spies[1].calls) == 1


class Boom:
    def __init__(self, error: BaseException) -> None:
        self.error = error

    def translate(self, text, edge, context=()):
        raise self.error


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (
            CapabilityMissingError(Requirement(RequirementKind.TRANSLATION, "de>zh-Hans")),
            FailureReason.MODEL,
        ),
        (FileNotFoundError("model"), FailureReason.MODEL),
        (MemoryError(), FailureReason.MEMORY),
        (RuntimeError("CUDA out of memory"), FailureReason.MEMORY),
        (ValueError(SECRET), FailureReason.OTHER),
    ],
)
def test_failures_map_to_a_reason_and_never_log_text(gui, caplog, error, reason) -> None:
    caplog.set_level(logging.DEBUG)
    jobs = TranslationJobs(lambda: Boom(error), gui.post)
    outcomes = Outcomes(DraftState(DE, ZH, SECRET))
    request = outcomes.start(jobs)
    gui.pump(outcomes.settled(request.request_id))
    jobs.shutdown()
    assert outcomes.failed == [(request.request_id, reason)]
    assert outcomes.draft.result is None
    assert SECRET not in caplog.text and "out of memory" not in caplog.text
    assert type(error).__name__ in caplog.text


def test_load_error_class_maps_to_model() -> None:
    from lianiq.translation.marian_engine import ModelLoadError

    assert failure_reason(ModelLoadError("x")) is FailureReason.MODEL
    assert failure_reason(OSError("x")) is FailureReason.MODEL


def test_shutdown_cancels_and_refuses_new_jobs(gui) -> None:
    spy = GatedSpy()
    jobs = TranslationJobs(lambda: spy, gui.post)
    outcomes = Outcomes(DraftState(DE, ZH, "Eins. Zwei."))
    request = outcomes.start(jobs)
    spy.wait_entered()
    releaser = threading.Timer(0.2, spy.gate.set)
    releaser.start()
    jobs.shutdown()
    releaser.join()
    gui.pump(outcomes.settled(request.request_id))
    assert outcomes.cancelled == [request.request_id]
    with pytest.raises(RuntimeError):
        outcomes.start(jobs)
