"""CAP-0170 WI-04: follow-the-bottom scrolling, Copy and Export on the Listen page."""
# ruff: noqa: F811 - ``spies`` is the imported fixture

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtGui import QGuiApplication

import lianiq.ui.workspaces.listen_actions as actions
from lianiq.listen.lifecycle import ListenPhase
from lianiq.listen.transcript import SegmentState
from lianiq.ui.shell.workspaces import WorkspaceId
from tests._spy_window import spies  # noqa: F401 - the fixture
from tests.ui._language_packs_helpers import wait_until
from tests.ui._listen_helpers import listen_window, phase_is, speak, start, states


@pytest.fixture
def window(tmp_path, monkeypatch, spies):
    window = listen_window(tmp_path, monkeypatch)
    yield window
    window.listen.shutdown()
    window.close()


def save_as(monkeypatch, path: str) -> None:
    monkeypatch.setattr(actions.QFileDialog, "getSaveFileName", lambda *a, **k: (path, ""))


def test_ac15_rows_follow_only_at_the_bottom(window, spies) -> None:
    start(window)
    bar = window.listen.transcript_view.verticalScrollBar()
    speak(window, spies, *[f"Satz {n}." for n in range(20)])
    assert wait_until(lambda: states(window).count(SegmentState.DONE) == 20)
    assert wait_until(lambda: bar.maximum() > 0 and bar.value() == bar.maximum())
    bar.setValue(0)
    speak(window, spies, "Neu.")
    assert wait_until(lambda: len(states(window)) == 21)
    assert bar.value() == 0 and window.listen.jump_button.isVisible()
    window.listen.jump_button.click()
    assert wait_until(lambda: bar.value() == bar.maximum())
    assert not window.listen.jump_button.isVisible()


def test_ac16_copy_and_export_hold_transcript_v2(window, spies, monkeypatch, tmp_path) -> None:
    page = window.listen
    assert not page.copy_button.isEnabled() and not page.export_button.isEnabled()
    start(window)
    speak(window, spies, "", "Guten Morgen.")
    assert wait_until(lambda: SegmentState.DONE in states(window))
    window.stop_active_session()
    assert phase_is(window, ListenPhase.IDLE)
    page.copy_button.click()
    text = QGuiApplication.clipboard().text()
    assert "[de>zh-Hans] Guten Morgen." in text
    target = tmp_path / "listen.txt"
    save_as(monkeypatch, str(target))
    page.export_button.click()
    assert target.read_text(encoding="utf-8") == text
    save_as(monkeypatch, "")  # cancelled: nothing written, no notice
    page.export_button.click()
    assert sorted(path.name for path in tmp_path.glob("*.txt")) == ["listen.txt"]
    save_as(monkeypatch, str(tmp_path / "missing" / "listen.txt"))
    page.export_button.click()
    keys = [notice.key for notice in window.notices.live(WorkspaceId.LISTEN)]
    assert "listen-and-translate.export-failed" in keys
