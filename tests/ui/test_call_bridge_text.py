"""The Call Bridge live text view (CAP-0166 AC-13, AC-14): bounded, memory only."""

from __future__ import annotations

import logging
import os
from datetime import datetime
from uuid import uuid4

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from lianiq.call_bridge.contracts import LaneId
from lianiq.domain import TranslationResult
from tests.call_bridge.support import DE, ZH


def result(n: int) -> TranslationResult:
    return TranslationResult(uuid4(), datetime.now(), f"Satz {n}", f"句子 {n}", DE, ZH, 0.1, 0.1)


@pytest.fixture
def view():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    from lianiq.ui.call_bridge_text import CallBridgeTextView

    QApplication.instance() or QApplication([])
    view = CallBridgeTextView()
    yield view
    view.deleteLater()


def test_ac14_the_view_keeps_200_turns_and_writes_nothing(view, tmp_path, monkeypatch, caplog):
    from PySide6.QtWidgets import QAbstractItemView

    monkeypatch.chdir(tmp_path)
    caplog.set_level(logging.DEBUG)
    assert view.empty_label.text() == "Nothing translated yet." and not view.list.isVisibleTo(view)
    for n in range(205):
        view.add_turn(LaneId.OUTBOUND if n % 2 else LaneId.INBOUND, result(n))
    turns = view.turns()
    assert len(turns) == 200
    assert turns[0] == "You → call\nSatz 5\n句子 5"  # the five oldest were dropped
    assert turns[-1].startswith("Call → you\nSatz 204")
    assert view.list.editTriggers() == QAbstractItemView.EditTrigger.NoEditTriggers
    assert caplog.records == [] and list(tmp_path.iterdir()) == []  # memory only
    view.clear()
    assert view.turns() == [] and view.empty_label.isVisibleTo(view)
