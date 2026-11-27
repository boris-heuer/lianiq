"""paired-transcript WI-02: Conversation on ``PairedTranscriptView`` (spec §2.2, §2.3, §3.4).

Paired rows with the recorded language names and no *Original*/*Translation* panels; the
owner generation bound at emit time (a late result after **New conversation** and a new
session adds no row, a late result after a normal **Stop** still does); **New conversation**
with and without unsaved turns; **Copy transcript**; **Export transcript** disabled without a
translated turn and its default file name.
"""
# ruff: noqa: F811 - ``spies`` is the imported fixture

from __future__ import annotations

import datetime as dt
import os
from uuid import uuid4

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from lianiq.domain import TranslationResult
from lianiq.languages import LanguageId
from tests._spy_window import build_window, spies  # noqa: F401
from tests.ui import _conversation_helpers as conv
from tests.ui._language_helpers import click, start, submit, transcript, wait_until

DE, ZH = LanguageId("de"), LanguageId("zh-Hans")


@pytest.fixture
def window(tmp_path, spies, monkeypatch):
    window = build_window(tmp_path, monkeypatch)
    yield window
    window.stop_listening()
    window.close()


def late_result(text: str) -> TranslationResult:
    now = dt.datetime.now().astimezone()
    return TranslationResult(uuid4(), now, text, f"[late] {text}", DE, ZH, 0.1, 0.1)


def emit(window, result: TranslationResult, generation: int) -> None:
    from PySide6.QtCore import QCoreApplication

    window.bridge.result.emit(result, generation)
    QCoreApplication.processEvents()


def confirm(window, monkeypatch, answer: bool) -> list[int]:
    asked: list[int] = []

    def ask(count: int) -> bool:
        asked.append(count)
        return answer

    monkeypatch.setattr(conv.view(window), "confirm_clear", ask)
    return asked


def test_turns_are_paired_rows_with_the_recorded_language_names(window, spies) -> None:
    for gone in ("source_panel", "target_panel", "source_text", "target_text"):
        assert not hasattr(window, gone) and not hasattr(window.conversation, gone)
    view = conv.view(window)
    assert view.placeholder.isVisibleTo(view) and view.placeholder.text()  # empty state
    assert not view.export_button.isEnabled() and not view.copy_all_button.isEnabled()
    assert view.clear_button.text() == "New conversation"

    start(window)
    submit(window, spies, transcript("Guten Tag", "de"))
    assert wait_until(lambda: len(window.history) == 1)
    submit(window, spies, transcript("你好", "zh-Hans"))
    assert wait_until(lambda: len(window.history) == 2)

    assert conv.originals(window) == ["German: Guten Tag", "Mandarin (Simplified): 你好"]
    assert conv.translations(window) == [
        "Mandarin (Simplified): [de>zh-Hans] Guten Tag",
        "German: [zh-Hans>de] 你好",
    ]
    assert isinstance(window.history, tuple) and view.model.rowCount() == 2
    assert not view.placeholder.isVisibleTo(view)
    assert view.export_button.isEnabled() and view.copy_all_button.isEnabled()


def test_a_late_result_after_new_conversation_and_a_new_session_adds_no_row(
    window, spies, monkeypatch
) -> None:
    asked = confirm(window, monkeypatch, True)
    start(window)
    first = window.conversation._generation
    submit(window, spies, transcript("Guten Tag", "de"))
    assert wait_until(lambda: len(window.history) == 1)

    click(conv.view(window).clear_button)
    assert asked == [1] and not window.capture.running  # stopped, then cleared
    assert window.conversation.turns.rows == () and window.history == ()

    start(window)
    second = window.conversation._generation
    assert second != first
    emit(window, late_result("Verspätet"), first)  # emitted before the clear, queued
    assert window.history == ()
    submit(window, spies, transcript("Neuer Satz", "de"))
    assert wait_until(lambda: len(window.history) == 1)
    assert conv.originals(window) == ["German: Neuer Satz"]


def test_a_result_queued_at_a_normal_stop_still_appears(window, spies) -> None:
    start(window)
    generation = window.conversation._generation
    click(window.stop_button)
    assert not window.capture.running
    emit(window, late_result("Noch übersetzt"), generation)
    assert conv.originals(window) == ["German: Noch übersetzt"]


def test_new_conversation_asks_only_for_unsaved_turns(window, spies, monkeypatch) -> None:
    asked = confirm(window, monkeypatch, False)
    view = conv.view(window)
    start(window)
    submit(window, spies, transcript("Guten Tag", "de"))
    assert wait_until(lambda: len(window.history) == 1)

    click(view.clear_button)  # Cancel: nothing changes, the session keeps running
    assert asked == [1] and window.capture.running and len(window.history) == 1

    window.conversation.turns.mark_exported(r.turn_id for r in window.history)
    click(view.clear_button)  # every turn exported: no question
    assert asked == [1]
    assert not window.capture.running and window.history == ()
    assert not view.clear_button.isEnabled() and not view.export_button.isEnabled()
    assert view.current_turn() is None


def test_copy_transcript_and_the_export_default_name(window, spies, monkeypatch) -> None:
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QFileDialog

    start(window)
    submit(window, spies, transcript("Guten Tag", "de"))
    assert wait_until(lambda: len(window.history) == 1)
    view = conv.view(window)
    click(view.copy_all_button)
    pair = window.conversation.pair_for_export()
    assert QGuiApplication.clipboard().text() == window.conversation.turns.transcript_text(pair)

    offered = []

    def save(_parent, _title, default, _filter):
        offered.append(default)
        return "", ""

    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(save))
    click(view.export_button)
    today = dt.datetime.now().astimezone().date().isoformat()
    assert offered and offered[0].endswith(f"conversation-{today}.txt")
    assert window.conversation.turns.unsaved_count() == 1  # cancelled: nothing saved
