"""Results stay visible during and after a screen-reader session (lianiq#69, WI-08).

Native finding: after Narrator read the former *Original* and *Translation* panels, every
later turn was recognised and translated but neither panel showed it. Since paired-transcript
WI-02 the turns are rows of the *Transcript* list. A screen reader selects the row it reads
(UI Automation ``SelectionItem.Select``; ``PairedTranscriptView.select_row`` is that path),
and that selection never moves the view, so a list at its end still follows every later turn.

Offscreen these tests are code evidence; the native check ran with a UI Automation client
and Narrator.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tests._spy_window import build_window, spies  # noqa: F401
from tests.ui import _conversation_helpers as conv
from tests.ui._language_helpers import start, submit, transcript, wait_until


@pytest.fixture
def window(tmp_path, spies, monkeypatch):  # noqa: F811
    window = build_window(tmp_path, monkeypatch)
    yield window
    window.stop_listening()
    window.close()


def fill_rows(window, spies, turns: int) -> None:  # noqa: F811
    for turn in range(turns):
        submit(window, spies, transcript(f"Satz Nummer {turn}", "de"))
        assert wait_until(lambda expected=turn + 1: len(window.history) == expected)


def test_results_stay_visible_after_a_screen_reader_read_the_list(window, spies) -> None:  # noqa: F811
    start(window)
    fill_rows(window, spies, 8)
    listing = conv.view(window).list
    assert wait_until(lambda: listing.verticalScrollBar().maximum() > 0), "the list must overflow"
    assert wait_until(lambda: conv.list_at_end(window))
    conv.view(window).select_row(0)  # the screen reader reads the first row
    assert conv.list_at_end(window)  # the selection did not move the view

    submit(window, spies, transcript("Neuer Satz nach dem Vorlesen", "de"))
    assert wait_until(lambda: len(window.history) == 9)
    assert wait_until(lambda: conv.list_at_end(window) and conv.last_row_visible(window))
    assert conv.originals(window)[-1] == "German: Neuer Satz nach dem Vorlesen"
    assert conv.translations(window)[-1].startswith("Mandarin (Simplified): [de>zh-Hans] Neuer")
    assert conv.view(window).current_turn() is window.conversation.turns.rows[0]  # kept


def test_every_later_result_is_shown_while_the_screen_reader_keeps_reading(
    window,
    spies,  # noqa: F811
) -> None:
    start(window)
    fill_rows(window, spies, 6)
    for turn in range(3):
        conv.view(window).select_row(turn)
        expected = 7 + turn
        submit(window, spies, transcript(f"Weiterer Satz {turn}", "de"))
        assert wait_until(lambda expected=expected: len(window.history) == expected)
        assert wait_until(lambda: conv.last_row_visible(window))
        assert conv.originals(window)[-1] == f"German: Weiterer Satz {turn}"
