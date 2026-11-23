"""CAP-0170 WI-08 (AC-30): UIA names, row text and keyboard operation of the Listen page.

Offscreen through ``QAccessible``: every tab stop of the page has an accessible name equal
to its visible caption, the list is named *Transcript* and each row exposes the spec §2.3
text. VoR-01..03 by keyboard only: Ctrl+4 opens the page, F8 starts, Ctrl+7 leaves for
Settings while rows arrive, Ctrl+4 returns, F9 stops; Tab order is setup row → Start →
transcript → actions. The native UIA row stays with the operator run (AC-32).
"""
# ruff: noqa: F811 - ``spies`` is the imported fixture

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QLabel

from lianiq.listen.lifecycle import ListenPhase
from lianiq.listen.transcript import SegmentState
from lianiq.ui import strings
from lianiq.ui.shell.workspaces import WorkspaceId
from tests._spy_window import spies  # noqa: F401 - the fixture
from tests.ui._language_packs_helpers import wait_until
from tests.ui._listen_helpers import listen_window, phase_is, speak, states
from tests.ui._navigation_helpers import activate, press
from tests.ui.test_main_window_accessibility import accessible_name, focused, tab_stops

LISTEN, SETTINGS = WorkspaceId.LISTEN, WorkspaceId.SETTINGS
CONTROL = Qt.KeyboardModifier.ControlModifier


@pytest.fixture
def window(tmp_path, monkeypatch, spies):
    window = listen_window(tmp_path, monkeypatch)
    activate(window)
    yield window
    window.listen.shutdown()
    window.close()


def page_stops(window) -> list:
    page = window.listen.page
    return [widget for widget in tab_stops(window) if page.isAncestorOf(widget)]


def caption(widget) -> str:
    """The visible caption: a button's text, or the text of the label buddied to a combo."""
    if isinstance(widget, QComboBox):
        labels = widget.parentWidget().findChildren(QLabel)
        return next(label.text() for label in labels if label.buddy() is widget)
    return widget.text() if hasattr(widget, "text") else ""


def test_ac30_every_control_is_named_after_its_caption(window) -> None:
    page = window.listen
    stops = page_stops(window)
    assert page.start_button in stops and page.transcript_view in stops
    for widget in stops:
        name = accessible_name(widget)
        assert name.strip(), type(widget).__name__
        if widget is not page.transcript_view:
            assert name == caption(widget), name
    assert accessible_name(page.transcript_view) == strings.LISTEN_TRANSCRIPT


def test_ac30_rows_expose_the_section_2_3_text(window, spies) -> None:
    window.start_listening()
    assert phase_is(window, ListenPhase.LISTENING)
    speak(window, spies, "Guten Morgen.")
    assert wait_until(lambda: states(window) == [SegmentState.DONE])
    row = window.listen.controller.transcript.rows[0]
    index = window.listen.model.index(0)
    text = index.data(Qt.ItemDataRole.AccessibleTextRole)
    time = row.captured_at.strftime("%H:%M:%S")
    translated = row.result.translated_text
    assert text == f"{time}, German: Guten Morgen.. Mandarin (Simplified): {translated}"


def test_ac30_tab_order_is_setup_start_transcript_actions(window) -> None:
    page = window.listen
    order = [
        page.source_combo,
        page.swap_button,
        page.target_combo,
        page.microphone_combo,
        page.start_button,
        page.transcript_view,
    ]
    order[0].setFocus()
    assert wait_until(lambda: focused() is order[0])
    reached = [focused()]
    for _ in range(len(order) - 1):
        press(focused(), Qt.Key.Key_Tab)
        reached.append(focused())
    expected = [widget for widget in order if widget in page_stops(window)]
    assert [widget for widget in reached if widget in expected] == expected


def test_ac30_vor_01_to_03_by_keyboard(window, spies) -> None:
    press(window, Qt.Key.Key_1, CONTROL)
    assert window.current_workspace() is WorkspaceId.CONVERSATION
    press(window, Qt.Key.Key_4, CONTROL)  # VoR-01: open the page, F8 starts
    assert window.current_workspace() is LISTEN
    press(window, Qt.Key.Key_F8)
    assert phase_is(window, ListenPhase.LISTENING)
    press(window, Qt.Key.Key_7, CONTROL)  # VoR-03: listening continues while away
    assert window.current_workspace() is SETTINGS
    speak(window, spies, "Hallo.")
    assert wait_until(lambda: states(window) == [SegmentState.DONE])
    press(window, Qt.Key.Key_4, CONTROL)
    assert window.current_workspace() is LISTEN
    press(window, Qt.Key.Key_F9)  # VoR-02: Stop; the text stays
    assert phase_is(window, ListenPhase.IDLE)
    assert states(window) == [SegmentState.DONE]
    assert window.listen.start_button.isEnabled()
