"""CAP-0172 rev 1.1 (lianiq#35): progress of a long translation on the real page (AC-40)."""

from __future__ import annotations

import pytest

from lianiq.text_translation.limits import MAX_SOURCE_CODE_POINTS
from lianiq.ui import strings
from lianiq.ui.shell.workspaces import WorkspaceId
from tests._spy_window import build_window, spies  # noqa: F401 - pytest fixture
from tests.text_translation._text_helpers import GatedSpy
from tests.ui._language_helpers import wait_until


@pytest.fixture
def gated():
    spy = GatedSpy()
    yield spy
    spy.gate.set()


@pytest.fixture
def page(tmp_path, spies, monkeypatch, gated):  # noqa: F811 - the spies fixture
    window = build_window(tmp_path, monkeypatch, provisioned=False)
    window.navigation.select(WorkspaceId.TEXT_TRANSLATION)
    workspace = window.text_translation
    workspace.jobs._translator = lambda: gated
    yield workspace
    window.close()


def test_ac40_status_and_bar_show_the_part_until_the_result_shows(page, gated) -> None:
    page.source_edit.setPlainText("Eins. Zwei. Drei. Vier.")
    page.translate_button.click()
    gated.wait_entered()
    expected = strings.TEXT_PROGRESS.format(done=1, total=4, percent=0)
    assert wait_until(lambda: page.status_label.text() == expected)
    assert page.busy_indicator.maximum() == 4 and page.busy_indicator.value() == 0
    gated.gate.set()
    gated.wait_entered()
    assert wait_until(lambda: not page.controller.translating)
    assert page.busy_indicator.isHidden()
    assert page.result_edit.toPlainText() == "Eins. Zwei. Drei. Vier."


def test_ac39_the_counter_and_translate_follow_the_new_limit(page) -> None:
    page.source_edit.setPlainText("a" * MAX_SOURCE_CODE_POINTS)
    assert page.translate_button.isEnabled()
    assert page.counter_label.text() == strings.TEXT_COUNTER.format(
        count=MAX_SOURCE_CODE_POINTS, limit=MAX_SOURCE_CODE_POINTS
    )
    page.source_edit.setPlainText("a" * (MAX_SOURCE_CODE_POINTS + 1))
    assert not page.translate_button.isEnabled()
