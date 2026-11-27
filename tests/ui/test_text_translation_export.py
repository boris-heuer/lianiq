"""CAP-0172 rev 1.1 (lianiq#35): Export translation… to a file the user chooses (AC-41, AC-42)."""

from __future__ import annotations

import pytest

from lianiq.ui import strings
from lianiq.ui.shell.workspaces import WorkspaceId
from lianiq.ui.workspaces import text_translation as module
from tests._spy_window import build_window, spies  # noqa: F401 - pytest fixture
from tests.ui._language_helpers import wait_until

TEXT = WorkspaceId.TEXT_TRANSLATION
SOURCE = "Erster Absatz.\n\n中文。"


@pytest.fixture
def window(tmp_path, spies, monkeypatch):  # noqa: F811 - the spies fixture
    window = build_window(tmp_path, monkeypatch, provisioned=False)
    window.navigation.select(TEXT)
    yield window
    window.close()


def save_as(monkeypatch, path: str, seen: list | None = None) -> None:
    def dialog(_parent, _title, default, _filter):
        if seen is not None:
            seen.append(default)
        return path, ""

    monkeypatch.setattr(module.QFileDialog, "getSaveFileName", dialog)


def translate(page) -> str:
    page.source_edit.setPlainText(SOURCE)
    page.translate_button.click()
    assert wait_until(lambda: page.controller.current_translation() is not None)
    return page.controller.current_translation()


def test_ac41_export_writes_the_current_translation_as_utf8(window, monkeypatch, tmp_path) -> None:
    page = window.text_translation
    assert not page.export_button.isEnabled()  # no result yet
    result = translate(page)
    assert page.export_button.isEnabled()
    target, seen = tmp_path / "out.txt", []
    save_as(monkeypatch, str(target), seen)
    page.export_button.click()
    assert target.read_text(encoding="utf-8") == result
    assert seen[0].endswith(".txt") and "translation-de-zh-Hans-" in seen[0]
    assert window.statusBar().currentMessage() == strings.TEXT_SAVED.format(path=str(target))
    save_as(monkeypatch, "")  # cancelled: nothing written
    page.export_button.click()
    assert [p.name for p in tmp_path.glob("*.txt")] == ["out.txt"]
    page.source_edit.insertPlainText(" mehr")  # stale: no export
    assert not page.export_button.isEnabled()


def test_ac42_a_failed_save_shows_a_notice_without_user_text(window, monkeypatch, tmp_path) -> None:
    page = window.text_translation
    translate(page)
    save_as(monkeypatch, str(tmp_path / "missing" / "out.txt"))
    page.export_button.click()
    live = window.notices.live(TEXT)
    assert "text-translation.export-failed" in [n.key for n in live]
    assert all("Absatz" not in n.title and "中文" not in n.title for n in live)
    assert page.source_edit.toPlainText() == SOURCE
    save_as(monkeypatch, str(tmp_path / "ok.txt"))
    page.export_button.click()
    assert "text-translation.export-failed" not in [n.key for n in window.notices.live(TEXT)]
