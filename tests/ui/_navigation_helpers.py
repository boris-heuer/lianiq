"""Shared helpers for the shell navigation tests (CAP-0168 WI-02; ``test_shell_navigation*.py``).

The offscreen ``window`` fixture over spy adapters, keyboard and resize helpers, and
``fill`` for appending recognised turns; also used by the shell layout and settings tests.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from lianiq.ui.shell.workspaces import WorkspaceId
from tests._spy_window import build_window
from tests.ui._language_helpers import submit, transcript, wait_until

PLANNED = (WorkspaceId.TEXT_TRANSLATION, WorkspaceId.LISTEN, WorkspaceId.LANGUAGE_PACKS)
ENABLED = (WorkspaceId.CONVERSATION, WorkspaceId.CALL_BRIDGE, WorkspaceId.SETTINGS)


# The explicit name keeps the fixture "window" for test modules importing this function.
# It requests ``spies``, which the test module imports from ``tests/_spy_window.py``.
@pytest.fixture(name="window")
def navigation_window(tmp_path, spies, monkeypatch):
    window = build_window(tmp_path, monkeypatch)
    yield window
    window.stop_listening()
    window.close()


def press(widget, key, modifier=None) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    QTest.keyClick(widget, key, modifier or Qt.KeyboardModifier.NoModifier)


def activate(window) -> None:
    from PySide6.QtWidgets import QApplication

    window.activateWindow()
    assert wait_until(lambda: QApplication.activeWindow() is window)


def resize(window, width: int, height: int) -> None:
    from PySide6.QtTest import QTest

    window.resize(width, height)
    QTest.qWait(30)
    assert (window.width(), window.height()) == (width, height)


def fill(window, spies, turns: int) -> None:
    """Append ``turns`` recognised German turns, one at a time."""
    for turn in range(turns):
        submit(window, spies, transcript(f"Satz Nummer {turn}", "de"))
        assert wait_until(lambda expected=turn + 1: len(window.history) == expected)


def texts_in(widget) -> list[str]:
    from PySide6.QtWidgets import QAbstractButton, QComboBox, QLabel

    found = [label.text() for label in widget.findChildren(QLabel)]
    found += [button.text() for button in widget.findChildren(QAbstractButton)]
    for combo in widget.findChildren(QComboBox):
        found += [combo.accessibleName(), *(combo.itemText(i) for i in range(combo.count()))]
    return found
