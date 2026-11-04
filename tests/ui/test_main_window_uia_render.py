"""Results stay visible during and after a screen-reader session (lianiq#69, WI-08).

Native finding: after Narrator read the *Original* and *Translation* panels, every later
turn was recognised and translated but neither panel showed it. A screen reader selects and
scrolls to the text it reads (UI Automation ``TextRange.Select`` and ``ScrollIntoView``, which
Qt maps to ``QAccessibleTextInterface.setSelection`` and ``scrollToSubstring``). That leaves
the panel scrolled away from the end, and ``appendPlainText`` then appends out of view.

These tests drive the same accessibility interface Qt's UI Automation bridge calls. Offscreen
they are code evidence; the native check ran with a UI Automation client and Narrator.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tests.test_requirement_scoped_loading import build_window, spies  # noqa: F401
from tests.ui.test_main_window_languages import start, submit, transcript, wait_until


@pytest.fixture
def window(tmp_path, spies, monkeypatch):  # noqa: F811
    window = build_window(tmp_path, monkeypatch)
    yield window
    window.stop_listening()
    window.close()


def panels(window):
    return window.source_text, window.target_text


def at_end(panel) -> bool:
    bar = panel.verticalScrollBar()
    return bar.value() == bar.maximum()


def last_result_visible(panel, prefix: str) -> bool:
    """The last result line is inside the panel's viewport."""
    document = panel.document()
    block = document.lastBlock()
    while block.isValid() and not block.text().strip():
        block = block.previous()
    assert block.text().startswith(prefix)
    geometry = panel.blockBoundingGeometry(block).translated(panel.contentOffset())
    return geometry.intersects(panel.viewport().rect().toRectF())


def read_like_a_screen_reader(panel) -> None:
    """What Narrator does on a panel: select the first line and scroll it into view."""
    from PySide6.QtGui import QAccessible

    text = QAccessible.queryAccessibleInterface(panel).textInterface()
    first_line_end = panel.toPlainText().index("\n")
    text.setSelection(0, 0, first_line_end)
    text.scrollToSubstring(0, first_line_end)


def fill_panels(window, spies, turns: int) -> None:  # noqa: F811
    for turn in range(turns):
        submit(window, spies, transcript(f"Satz Nummer {turn}", "de"))
        assert wait_until(lambda expected=turn + 1: len(window.history) == expected)


def test_results_stay_visible_after_a_screen_reader_read_the_panels(window, spies) -> None:  # noqa: F811
    start(window)
    fill_panels(window, spies, 8)
    for panel in panels(window):
        assert panel.verticalScrollBar().maximum() > 0, "the panels must overflow"
        read_like_a_screen_reader(panel)
        assert not at_end(panel)

    submit(window, spies, transcript("Neuer Satz nach dem Vorlesen", "de"))
    assert wait_until(lambda: len(window.history) == 9)

    source, target = panels(window)
    assert at_end(source) and at_end(target)
    assert last_result_visible(source, "German: Neuer Satz nach dem Vorlesen")
    assert last_result_visible(target, "Mandarin (Simplified): [de>zh-Hans] Neuer Satz")
    # Only the view follows the result: the screen reader's selection is left alone.
    for panel in panels(window):
        assert panel.textCursor().hasSelection()


def test_every_later_result_is_shown_while_the_screen_reader_keeps_reading(
    window,
    spies,  # noqa: F811
) -> None:
    start(window)
    fill_panels(window, spies, 6)
    for turn in range(3):
        for panel in panels(window):
            read_like_a_screen_reader(panel)
        expected = 7 + turn
        submit(window, spies, transcript(f"Weiterer Satz {turn}", "de"))
        assert wait_until(lambda expected=expected: len(window.history) == expected)
        assert last_result_visible(window.source_text, f"German: Weiterer Satz {turn}")
        assert last_result_visible(window.target_text, "Mandarin (Simplified): [de>zh-Hans]")
