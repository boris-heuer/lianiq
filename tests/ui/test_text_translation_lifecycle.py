"""CAP-0172 WI-03: request lifecycle on the real page (offscreen, gated spy translator).

AC-16 (stale marker and Copy half), AC-17, AC-19, AC-20 and AC-21; the Play/Replay half of
AC-16 arrives with WI-04.
"""

from __future__ import annotations

import pytest

from lianiq.ui import strings
from lianiq.ui.notice_catalog_base import TRANSLATION_FAILED, model_failed_key
from lianiq.ui.shell.workspaces import WorkspaceId
from tests._spy_window import build_window, spies  # noqa: F401 - pytest fixture
from tests.text_translation._text_helpers import GatedSpy
from tests.ui._language_helpers import wait_until
from tests.ui._navigation_helpers import ENABLED

TEXT = WorkspaceId.TEXT_TRANSLATION


class Failing:
    def __init__(self, error: BaseException) -> None:
        self.error = error

    def translate(self, text, edge, context=()):
        raise self.error


@pytest.fixture
def gated():
    spy = GatedSpy()
    yield spy
    spy.gate.set()  # never leave the worker blocked


@pytest.fixture
def page(tmp_path, spies, monkeypatch, gated):  # noqa: F811 - the spies fixture
    window = build_window(tmp_path, monkeypatch, provisioned=False)
    window.navigation.select(TEXT)
    workspace = window.text_translation
    workspace.jobs._translator = lambda: gated
    yield workspace
    window.close()


def type_text(workspace, text: str) -> None:
    workspace.source_edit.setFocus()
    workspace.source_edit.insertPlainText(text)


def idle(workspace):
    return lambda: not workspace.controller.translating


def translate_now(workspace, gated) -> None:
    """One request that finishes at once."""
    gated.gate.set()
    workspace.translate_button.click()
    assert wait_until(idle(workspace))
    gated.wait_entered()  # consume this call's entry signal
    gated.gate.clear()


def test_running_shows_the_indicator_and_cancel(page, gated) -> None:
    type_text(page, "Läuft.")
    page.translate_button.click()
    gated.wait_entered()
    assert page.translate_button.text() == strings.TEXT_CANCEL
    assert page.status_label.text() == strings.TEXT_TRANSLATING
    assert not page.busy_indicator.isHidden() and page.busy_indicator.maximum() == 0
    gated.gate.set()
    assert wait_until(idle(page))
    assert page.busy_indicator.isHidden()
    assert page.translate_button.text() == strings.TEXT_TRANSLATE


def test_ac16_ac17_an_edit_marks_stale_and_a_new_request_wins(page, gated) -> None:
    type_text(page, "Eins.")
    translate_now(page, gated)
    type_text(page, " Zwei.")
    assert not page.stale_label.isHidden()  # same event-loop turn
    assert not page.copy_translation_button.isEnabled()
    page.translate_button.click()  # request A, held in the gate
    gated.wait_entered()
    type_text(page, " Drei.")
    assert page.translate_button.text() == strings.TEXT_TRANSLATE  # B may be requested
    page.translate_button.click()
    gated.gate.set()
    assert wait_until(lambda: page.result_edit.toPlainText().endswith("Drei."))
    assert wait_until(idle(page))
    assert page.stale_label.isHidden() and page.copy_translation_button.isEnabled()


def test_ac19_escape_cancels_and_retry_translates(page, gated) -> None:
    type_text(page, "Erst.")
    translate_now(page, gated)
    type_text(page, " Dann.")
    page.translate_button.click()
    gated.wait_entered()
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    QTest.keyClick(page.source_edit, Qt.Key.Key_Escape)
    gated.gate.set()
    assert wait_until(idle(page))
    assert page.status_label.text() == strings.TEXT_CANCELLED
    assert not page.retry_button.isHidden()
    assert page.result_edit.toPlainText().endswith("Erst.")  # unchanged
    page.retry_button.click()
    assert wait_until(lambda: page.result_edit.toPlainText().endswith("Erst. Dann."))
    assert page.retry_button.isHidden()


@pytest.mark.parametrize(
    ("translator", "key"),
    [
        (lambda: Failing(RuntimeError("Geheim.")), TRANSLATION_FAILED),
        (lambda: (_ for _ in ()).throw(OSError("Geheim.")), model_failed_key(TEXT)),
    ],
)
def test_ac20_a_failure_shows_a_notice_on_the_page(page, translator, key) -> None:
    page.jobs._translator = translator
    type_text(page, "Geheim.")
    page.translate_button.click()
    assert wait_until(idle(page))
    notice = page.host.notices.top(TEXT)
    assert notice is not None and notice.key == key
    assert "Geheim." not in notice.title + notice.detail
    assert page.source_edit.toPlainText() == "Geheim."
    assert not page.host.banners[TEXT].isHidden()
    assert not page.retry_button.isHidden()


def test_ac21_caret_and_selection_survive_every_change(page, gated) -> None:
    from PySide6.QtGui import QTextCursor

    type_text(page, "Der Satz bleibt.")
    cursor = page.source_edit.textCursor()
    cursor.setPosition(4)
    cursor.setPosition(8, QTextCursor.MoveMode.KeepAnchor)
    page.source_edit.setTextCursor(cursor)

    def unchanged() -> None:
        now = page.source_edit.textCursor()
        assert page.source_edit.toPlainText() == "Der Satz bleibt."
        assert (now.anchor(), now.position()) == (4, 8)

    translate_now(page, gated)  # result and status changes
    unchanged()
    page.translate_button.click()
    gated.wait_entered()
    page.translate_button.click()  # Cancel
    gated.gate.set()
    assert wait_until(idle(page))
    unchanged()
    page.jobs._translator = lambda: Failing(RuntimeError("x"))
    page.retry_button.click()  # retry, then failure
    assert wait_until(idle(page))
    unchanged()
    for workspace in ENABLED:
        page.host.navigation.select(workspace)
        page.host.navigation.select(TEXT)
        unchanged()
