"""CAP-0172 contract §3 and §8: the controller's request lifecycle (AC-17 to AC-20, unit halves)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from lianiq.text_translation.controller import TextTranslationController
from lianiq.text_translation.jobs import TranslationJobs
from lianiq.text_translation.state import ResultState
from lianiq.ui import strings
from lianiq.ui.notice_catalog_base import TRANSLATION_FAILED, model_failed_key
from lianiq.ui.shell.workspaces import WorkspaceId
from tests.languages.synthetic import provisioned_catalog
from tests.text_translation._text_helpers import (
    DE,
    ZH,
    GatedSpy,
    GuiThread,
    IdentitySpy,
    Speakers,
    three_language_registry,
)

SECRET = "Geheimer Satz."


@dataclass
class Page:
    """The notices and snapshots the controller hands to its page."""

    notices: list = field(default_factory=list)
    resolved: list = field(default_factory=list)
    snapshots: list = field(default_factory=list)


@pytest.fixture
def gui():
    return GuiThread()


def controller(tmp_path: Path, gui: GuiThread, translator, page: Page):
    registry = three_language_registry()
    catalog = provisioned_catalog(tmp_path, registry, edges=["de>zh-Hans", "zh-Hans>de"])
    # A translator instance, or a factory that builds (or fails to build) one.
    factory = translator if not hasattr(translator, "translate") else (lambda: translator)
    jobs = TranslationJobs(factory, gui.post)
    return TextTranslationController(
        registry,
        lambda: catalog,
        lambda: None,
        jobs,
        lambda: Speakers(True),
        page.snapshots.append,
        (DE, ZH),
        notify=page.notices.append,
        resolve=lambda keys: page.resolved.extend(keys),
    )


def idle(control):
    return lambda: not control.translating


def test_ac17_a_late_result_of_an_older_request_never_wins(tmp_path, gui) -> None:
    spy = GatedSpy()
    control = controller(tmp_path, gui, spy, Page())
    control.source_changed("Erster Satz.")
    control.translate()
    spy.wait_entered()
    assert control.cancellable and not control.can_translate()
    control.source_changed("Zweiter Satz.")
    assert not control.cancellable and control.can_translate()  # an edit allows request B
    control.translate()
    spy.gate.set()
    gui.pump(idle(control))
    assert control.draft.result.text == "Zweiter Satz."
    assert control.draft.result_state is ResultState.CURRENT
    control.shutdown()


def test_ac17_a_result_finishing_after_an_edit_is_discarded(tmp_path, gui) -> None:
    spy = GatedSpy()
    control = controller(tmp_path, gui, spy, Page())
    control.source_changed("Alt.")
    control.translate()
    gui.pump(lambda: spy.gate.set() or not control.translating)  # first result shown
    spy.gate.clear()
    control.source_changed("Alt. Neu.")
    control.translate()
    spy.wait_entered()
    control.source_changed("Alt. Neu. Noch neuer.")  # edit, no new request
    spy.gate.set()
    gui.pump(idle(control))
    assert control.draft.result.text == "Alt."
    assert control.draft.result_state is ResultState.STALE
    control.shutdown()


def test_ac18_rapid_edits_run_one_job_at_a_time_and_show_the_last(tmp_path, gui) -> None:
    spy = IdentitySpy(delay=0.002)
    control = controller(tmp_path, gui, spy, Page())
    for i in range(50):
        control.source_changed(f"Satz {i}. Noch ein Satz.")
        if i % 5 == 0:
            control.translate()
    control.translate()
    gui.pump(idle(control))
    assert spy.overlap == 1
    assert control.draft.result.text == "Satz 49. Noch ein Satz."
    assert control.draft.result_state is ResultState.CURRENT
    control.shutdown()


def test_ac19_cancel_keeps_the_result_and_retry_translates_the_current_revision(
    tmp_path, gui
) -> None:
    spy = GatedSpy()
    control = controller(tmp_path, gui, spy, Page())
    control.source_changed("Bleibt.")
    control.translate()
    gui.pump(lambda: spy.gate.set() or not control.translating)
    spy.gate.clear()
    control.source_changed("Bleibt. Neu.")
    control.translate()
    spy.wait_entered()
    control.cancel()
    spy.gate.set()
    gui.pump(idle(control))
    snapshot = control.snapshot()
    assert snapshot.status == strings.TEXT_CANCELLED and snapshot.retry
    assert control.draft.result.text == "Bleibt."
    control.retry()
    gui.pump(idle(control))
    assert control.draft.result.text == "Bleibt. Neu."
    assert control.draft.result_state is ResultState.CURRENT
    control.shutdown()


class Failing:
    def __init__(self, error: BaseException) -> None:
        self.error = error

    def translate(self, text, edge, context=()):
        raise self.error


@pytest.mark.parametrize(
    ("factory", "key", "reason"),
    [
        (lambda: Failing(RuntimeError(SECRET)), TRANSLATION_FAILED, strings.TEXT_REASON_OTHER),
        (lambda: Failing(MemoryError()), TRANSLATION_FAILED, strings.TEXT_REASON_MEMORY),
        (
            lambda: (_ for _ in ()).throw(OSError(SECRET)),  # the model cannot be loaded
            model_failed_key(WorkspaceId.TEXT_TRANSLATION),
            strings.TEXT_REASON_MODEL,
        ),
    ],
)
def test_ac20_failures_post_a_notice_without_user_text(tmp_path, gui, factory, key, reason) -> None:
    page = Page()
    control = controller(tmp_path, gui, factory, page)
    control.source_changed(SECRET)
    control.translate()
    gui.pump(idle(control))
    (notice,) = page.notices
    assert notice.key == key and reason in notice.title
    assert notice.source == "Text translation · German → Mandarin (Simplified)"
    assert all(SECRET not in text for text in (notice.title, notice.detail, notice.source))
    assert notice.actions[0].label == strings.NOTICE_RETRY
    assert control.draft.text == SECRET and control.snapshot().retry
    control.translate()  # the next request resolves the failure notices
    assert TRANSLATION_FAILED in page.resolved
    gui.pump(idle(control))
    control.shutdown()
