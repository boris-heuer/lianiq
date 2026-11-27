"""The RES-06 Conversation layout (CAP-0168 WI-02; spec §2.3.3).

pytest-qt style offscreen UI tests: AC-09 (lines of the *Transcript* list at 1280×720 and
850×560), AC-10 (follow latest, paired-transcript WI-02: user scrolling stops following and
shows **Jump to latest**; a programmatic or UI Automation selection never moves the view) and AC-11 (held-turn excerpt of at least 20 characters at 850 px, full text
in the tooltip). Widths are measured with Segoe UI, as in the WI-08 layout tests. The Native
half of AC-09 is proven in WI-06.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tests._spy_window import build_window, spies  # noqa: F401
from tests.ui._language_helpers import start, submit, transcript, wait_until
from tests.ui._language_helpers import transcript as transcript_of
from tests.ui._navigation_helpers import fill, resize
from tests.ui.test_main_window_session import click
from tests.ui.test_main_window_wi08_fixes import (  # noqa: F401 - autouse Segoe UI fixture
    _load_windows_ui_font,
    clipped,
    use_windows_ui_font,
)


@pytest.fixture
def window(tmp_path, spies, monkeypatch):  # noqa: F811
    window = build_window(tmp_path, monkeypatch)
    use_windows_ui_font(window)
    yield window
    window.stop_listening()
    window.close()


def visible_lines(view) -> int:
    """Whole text lines the *Transcript* list's viewport shows."""
    from PySide6.QtGui import QFontMetrics

    listing = view.list
    return int(listing.viewport().height() // QFontMetrics(listing.font()).lineSpacing())


def at_end(view) -> bool:
    bar = view.list.verticalScrollBar()
    return bar.value() == bar.maximum()


def wheel_up(widget) -> None:
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtWidgets import QApplication

    viewport = widget.viewport()
    position = QPointF(viewport.rect().center())
    event = QWheelEvent(
        position,
        QPointF(viewport.mapToGlobal(position.toPoint())),
        QPoint(0, 0),
        QPoint(0, 360),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    QApplication.sendEvent(viewport, event)


def settle() -> None:
    from PySide6.QtTest import QTest

    QTest.qWait(20)


def view(window):
    return window.conversation.paired_view


# AC-09 ------------------------------------------------------------------------------------


@pytest.mark.parametrize(("size", "minimum"), [((1280, 720), 8), ((850, 560), 4)])
@pytest.mark.parametrize("running", [False, True], ids=["stopped", "running"])
def test_ac09_the_transcript_list_shows_enough_lines(window, size, minimum, running) -> None:
    if running:
        start(window)  # the session strip takes its row
        assert window.session_strip.isVisible()
    resize(window, *size)
    transcript = view(window)
    assert transcript.list.isVisible()
    assert visible_lines(transcript) >= minimum, (size, visible_lines(transcript))


def test_ac09_the_transcript_is_the_dominant_area(window) -> None:
    resize(window, 1280, 720)
    page = window.workspace_pages[window.current_workspace()]
    assert view(window).height() >= 0.6 * page.height()  # the list fills the rest


# AC-10 (paired-transcript §2.2.1 step 2: the list follows only while it is at its end) -----


def test_ac10_wheel_up_keeps_the_view_and_jump_to_latest_follows_again(
    window,
    spies,  # noqa: F811
) -> None:
    resize(window, 1280, 720)
    start(window)
    fill(window, spies, 14)
    transcript = view(window)
    bar = transcript.list.verticalScrollBar()
    assert wait_until(lambda: bar.maximum() > 0 and at_end(transcript))

    wheel_up(transcript.list)
    settle()
    assert not at_end(transcript)
    kept = bar.value()
    submit(window, spies, transcript_of("Neuer Satz", "de"))
    assert wait_until(lambda: len(window.history) == 15)
    settle()
    assert bar.value() == kept  # the view stays where the user left it
    assert transcript.jump_button.isVisible() and transcript.new_below_label.isVisible()

    click(transcript.jump_button)
    settle()
    assert at_end(transcript) and not transcript.jump_button.isVisible()
    submit(window, spies, transcript_of("Noch ein Satz", "de"))
    assert wait_until(lambda: len(window.history) == 16)
    assert wait_until(lambda: at_end(transcript))


@pytest.mark.parametrize("key", ["Key_Home"])
def test_ac10_keyboard_scrolling_up_stops_following(window, spies, key) -> None:  # noqa: F811
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    resize(window, 1280, 720)
    start(window)
    fill(window, spies, 14)
    transcript = view(window)
    assert wait_until(lambda: at_end(transcript))
    transcript.list.setFocus()
    transcript.select_row(13)
    QTest.keyClick(transcript.list, getattr(Qt.Key, key))
    settle()

    assert not at_end(transcript)
    kept = transcript.list.verticalScrollBar().value()
    submit(window, spies, transcript_of("Neuer Satz", "de"))
    assert wait_until(lambda: len(window.history) == 15)
    settle()
    assert transcript.list.verticalScrollBar().value() == kept


def test_ac10_programmatic_selection_never_moves_the_view(window, spies) -> None:  # noqa: F811
    resize(window, 1280, 720)
    start(window)
    fill(window, spies, 14)
    transcript = view(window)
    assert wait_until(lambda: at_end(transcript))
    transcript.select_row(0)  # the UI Automation selection path
    settle()
    assert at_end(transcript)

    submit(window, spies, transcript_of("Neuer Satz", "de"))
    assert wait_until(lambda: len(window.history) == 15)
    assert wait_until(lambda: at_end(transcript))
    assert transcript.current_turn() is window.conversation.turns.rows[0]  # kept


# AC-11 ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "spoken",
    [
        "Could you please repeat the last sentence slowly, because the line was very noisy?",
        "请您再慢慢地重复一遍最后一句话，因为刚才线路的噪音非常大，我没有听清楚。",
    ],
    ids=["latin", "cjk"],
)
def test_ac11_the_held_turn_excerpt_shows_20_characters_at_850_px(
    window,
    spies,  # noqa: F811
    spoken,
) -> None:
    from lianiq.ui.held_turn_bar import EXCERPT_MIN_CHARS

    resize(window, 850, 560)
    start(window)
    submit(window, spies, transcript(spoken, "en"))
    submit(window, spies, transcript("Second unclear turn", "en"))
    bar = window.held_turn_bar
    assert wait_until(lambda: bar.isVisible() and bar.counter_label.isVisible())
    resize(window, 850, 560)

    shown = bar.transcript_label.text()
    characters = shown.removeprefix("“").removesuffix("…").removesuffix("”")
    assert len(characters) >= EXCERPT_MIN_CHARS == 20, shown
    assert spoken.startswith(characters)
    assert bar.transcript_label.toolTip() == spoken  # the full sentence
    label = bar.transcript_label
    assert label.fontMetrics().horizontalAdvance(shown) <= label.contentsRect().width()
    assert clipped(bar) == []  # the buttons keep their full labels
    assert bar.mapTo(window, bar.rect().topRight()).x() <= window.width()
