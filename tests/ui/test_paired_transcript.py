"""paired-transcript WI-01: ``PairedTranscriptView`` offscreen over a fake host (spec §2, §3.2).

Copy texts and "Copied", Ctrl+C and the context menu keys, follow and **Jump to latest**,
the clear confirmation, export cancel and failure, a 2,000-row insert, RTL and CJK text, and
**Clear transcript** on the real Listen page (stop first, late callbacks ignored).
"""
# ruff: noqa: F811 - ``spies`` is the imported fixture

from __future__ import annotations

import os
import statistics
import time
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog, QMainWindow, QMessageBox

from lianiq.domain import TranslationResult
from lianiq.listen.lifecycle import ListenPhase
from lianiq.listen.session import listen_session
from lianiq.transcript import TurnLog, TurnState
from lianiq.ui import strings
from lianiq.ui.shell.workspaces import WorkspaceId
from lianiq.ui.transcript import PairedTranscriptView
from tests._spy_window import spies  # noqa: F401 - the fixture
from tests.text_translation._text_helpers import DE, ZH, three_language_registry
from tests.ui._language_packs_helpers import wait_until
from tests.ui._listen_helpers import listen_window, phase_is, speak, start, states

REGISTRY = three_language_registry()
PAIR = REGISTRY.pair(DE, ZH)
T0 = datetime(2026, 11, 27, 9, 0, tzinfo=UTC)
RTL = "שלום עולם"


class Diagnostics:
    def __init__(self) -> None:
        self.records: list[str] = []

    def record(self, _category: str, message: str) -> None:
        self.records.append(message)

    def redact(self, text: str) -> str:
        return text


class Notices:
    def __init__(self) -> None:
        self.resolved: list[str] = []

    def resolve(self, key: str) -> None:
        self.resolved.append(key)


class Host:
    workspace = WorkspaceId.LISTEN
    export_prefix = "listen"

    def __init__(self, log: TurnLog) -> None:
        self.log, self.notices, self.cleared = log, [], 0
        self.main_window = QMainWindow()
        self.main_window.diagnostics = Diagnostics()
        self.main_window.notices = Notices()

    def pair_for_export(self):
        return PAIR

    def replay_block(self, _turn):
        return None

    def replay(self, _turn) -> None: ...

    def stop_playback(self) -> None: ...

    def playing(self) -> bool:
        return False

    def clear_session(self) -> None:
        self.cleared += 1
        self.log.clear()

    def post_notice(self, notice) -> None:
        self.notices.append(notice)


def result(at, text="Guten Morgen.", out="早上好。") -> TranslationResult:
    return TranslationResult(uuid4(), at, text, out, DE, ZH, 0.1, 0.1)


def add(view: PairedTranscriptView, *texts: str, start: int = 0, session: int = 1) -> None:
    for offset, text in enumerate(texts):
        at = T0 + timedelta(seconds=start + offset)
        view.sync((view.log.add_result(result(at, text), session),))


@pytest.fixture
def view():
    QApplication.instance() or QApplication([])
    log = TurnLog()
    host = Host(log)
    view = PairedTranscriptView(log, REGISTRY, strings.TRANSCRIPT_CLEAR, host)
    view.resize(500, 300)
    view.show()
    yield view
    view.close()
    host.main_window.close()


def settle() -> None:
    for _ in range(5):
        QCoreApplication.processEvents()


def test_per_turn_copy_texts_ctrl_c_and_copied(view) -> None:
    add(view, "Guten Morgen.")
    turn_id = uuid4()
    view.log.captured(turn_id, T0 + timedelta(seconds=5), listen_session(PAIR, DE), 1)
    view.log.recognized(turn_id, "Noch nicht")
    view.sync((1,))
    assert not view.copy_pair_button.isEnabled()  # nothing selected
    view.select_row(0)
    view.copy_translation_button.click()
    assert QGuiApplication.clipboard().text() == "早上好。"
    assert view.copy_translation_button.text() == strings.TRANSCRIPT_COPIED
    assert view.copy_translation_button.accessibleName() == strings.TRANSCRIPT_COPY_TRANSLATION
    view.copy_original_button.click()
    assert QGuiApplication.clipboard().text() == "Guten Morgen."
    QTest.keyClick(view.list, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    expected = "German: Guten Morgen.\nMandarin (Simplified): 早上好。"
    assert QGuiApplication.clipboard().text() == expected
    assert view.copy_pair_button.text() == strings.TRANSCRIPT_COPIED
    assert wait_until(lambda: view.copy_pair_button.text() == strings.TRANSCRIPT_COPY_PAIR)
    view.select_row(1)  # not translated: only Copy original
    assert view.copy_original_button.isEnabled()
    assert not view.copy_translation_button.isEnabled() and not view.copy_pair_button.isEnabled()
    assert not view.replay_button.isVisible() and not view.stop_playback_button.isVisible()


@pytest.mark.parametrize("key", ["menu", "shift_f10"])
def test_context_menu_opens_by_keyboard(view, key) -> None:
    add(view, "Hallo.")
    view.select_row(0)
    if key == "menu":
        QTest.keyClick(view.list, Qt.Key.Key_Menu)
    else:
        QTest.keyClick(view.list, Qt.Key.Key_F10, Qt.KeyboardModifier.ShiftModifier)
    menu = view.menu
    visible = [a.text() for a in menu.actions() if a.isVisible()]
    copies = [strings.TRANSCRIPT_COPY_ORIGINAL, strings.TRANSCRIPT_COPY_TRANSLATION]
    assert visible == [*copies, strings.TRANSCRIPT_COPY_PAIR]
    menu.actions()[2].trigger()
    assert QGuiApplication.clipboard().text().startswith("German: Hallo.\n")
    menu.close()


def test_follow_jump_and_selection_never_moves_the_view(view) -> None:
    bar = view.list.verticalScrollBar()
    add(view, *[f"Satz {n}." for n in range(30)])
    assert wait_until(lambda: bar.maximum() > 0 and bar.value() == bar.maximum())
    assert not view.jump_button.isVisible()
    bar.setValue(0)
    add(view, "Neu.", start=100)
    settle()
    assert bar.value() == 0
    assert view.jump_button.isVisible() and view.new_below_label.isVisible()
    view.select_row(30)  # programmatic selection: the view stays
    settle()
    assert bar.value() == 0
    view.jump_button.click()
    assert wait_until(lambda: bar.value() == bar.maximum())
    assert not view.jump_button.isVisible()


def test_clear_asks_only_for_unsaved_turns_and_cancel_is_default(view, monkeypatch) -> None:
    add(view, "Eins.", "Zwei.")
    boxes = []

    def answer(choice):
        def run(box):
            boxes.append(box)
            assert box.defaultButton() is box.escapeButton()
            assert box.defaultButton() is box.button(QMessageBox.StandardButton.Cancel)
            assert box.text() == strings.TRANSCRIPT_CLEAR_TEXT.format(count=2)
            (box.confirm_button if choice else box.defaultButton()).click()
            return 0

        monkeypatch.setattr(QMessageBox, "exec", run)

    answer(False)
    view.clear_button.click()
    assert len(view.log.rows) == 2 and view.host.cleared == 0
    answer(True)
    view.clear_button.click()
    assert view.log.rows == () and view.host.cleared == 1 and view.model.rowCount() == 0
    assert not view.clear_button.isEnabled() and not view.copy_all_button.isEnabled()
    assert view.current_turn() is None and not view.copy_original_button.isEnabled()
    add(view, "Drei.", start=10, session=2)  # the cleared session 1 is finished
    view.log.mark_exported(r.turn_id for r in view.log.results())
    view.clear_button.click()  # everything exported: no question
    assert len(boxes) == 2 and view.log.rows == ()


def test_export_cancel_failure_and_success(view, monkeypatch, tmp_path) -> None:
    add(view, RTL)
    path = {"value": ""}
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (path["value"], ""))
    view.export_button.click()  # cancelled
    assert list(tmp_path.iterdir()) == [] and view.host.notices == []
    assert view.log.unsaved_count() == 1
    path["value"] = str(tmp_path / "missing" / "listen.txt")
    view.export_button.click()  # fails
    assert [n.key for n in view.host.notices] == ["listen-and-translate.export-failed"]
    assert view.log.unsaved_count() == 1 and len(view.log.rows) == 1
    assert view.host.main_window.statusBar().currentMessage() == ""
    path["value"] = str(tmp_path / "listen.txt")
    view.export_button.click()
    written = (tmp_path / "listen.txt").read_text(encoding="utf-8")
    assert RTL in written and "de -> zh-Hans" in written
    assert view.log.unsaved_count() == 0
    saved = strings.TRANSCRIPT_SAVED.format(path=path["value"])
    assert view.host.main_window.statusBar().currentMessage() == saved
    view.copy_all_button.click()
    assert QGuiApplication.clipboard().text() == written


def test_rtl_rows_align_right_and_keep_code_points(view) -> None:
    add(view, RTL, "你好，世界。")
    rtl, cjk = view.model.index(0), view.model.index(1)
    assert rtl.data(Qt.ItemDataRole.TextAlignmentRole) & Qt.AlignmentFlag.AlignRight
    assert not cjk.data(Qt.ItemDataRole.TextAlignmentRole) & Qt.AlignmentFlag.AlignRight
    view.select_row(0)
    view.copy_original_button.click()
    assert QGuiApplication.clipboard().text() == RTL
    assert RTL in rtl.data() and "你好，世界。" in cjk.data()


def test_2000_rows_insert_under_50_ms_without_reset(view) -> None:
    log = view.log
    for n in range(2000):
        log.add_result(result(T0 + timedelta(seconds=n), f"Satz {n}."), 1)
    view.sync(tuple(range(2000)))
    resets = []
    view.model.modelReset.connect(lambda: resets.append(1))
    timings = []
    for n in range(20):
        row = log.add_result(result(T0 + timedelta(seconds=5000 + n), "Neu."), 1)
        began = time.perf_counter()
        view.sync((row,))
        QCoreApplication.processEvents()
        timings.append(time.perf_counter() - began)
    assert statistics.median(timings) < 0.05 and resets == []


# The real Listen page.


@pytest.fixture
def window(tmp_path, monkeypatch, spies):
    window = listen_window(tmp_path, monkeypatch)
    yield window
    window.listen.shutdown()
    window.close()


def test_listen_clear_stops_the_session_and_ignores_late_callbacks(
    window, spies, monkeypatch
) -> None:
    page = window.listen
    assert page.clear_button.accessibleName() == strings.TRANSCRIPT_CLEAR
    assert not page.clear_button.isEnabled()
    start(window)
    speak(window, spies, "Guten Morgen.")
    assert wait_until(lambda: states(window) == [TurnState.DONE])
    stale = page.controller.transcript.rows[0].result
    generation = page.controller.transcript.rows[0].session_id
    monkeypatch.setattr(QMessageBox, "exec", lambda box: box.confirm_button.click() or 0)
    page.clear_button.click()
    assert phase_is(window, ListenPhase.IDLE)
    assert states(window) == [] and page.model.rowCount() == 0
    page.controller._completed(generation, stale)  # a late result of the cleared session
    assert states(window) == []
    assert page.empty_label.isVisible()
    start(window)
    speak(window, spies, "Hallo.")
    assert wait_until(lambda: states(window) == [TurnState.DONE])
