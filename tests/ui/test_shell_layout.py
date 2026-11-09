"""The RES-06 Conversation layout (CAP-0168 WI-02; spec §2.3.3).

pytest-qt style offscreen UI tests: AC-09 (transcript lines per panel at 1280×720 and
850×560), AC-10 (follow latest: user scrolling stops following, programmatic or UI
Automation scrolling never does; the lianiq#69 test in ``test_main_window_uia_render.py``
stays unchanged) and AC-11 (held-turn excerpt of at least 20 characters at 850 px, full text
in the tooltip). Widths are measured with Segoe UI, as in the WI-08 layout tests. The Native
half of AC-09 is proven in WI-06.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tests._spy_window import build_window, spies  # noqa: F401
from tests.ui._language_helpers import start, submit, transcript, wait_until
from tests.ui._navigation_helpers import fill, resize
from tests.ui.test_main_window_uia_render import read_like_a_screen_reader
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


def visible_lines(panel) -> int:
    """Whole transcript lines the panel's viewport shows."""
    from PySide6.QtGui import QFontMetrics

    document_margin = panel.document().documentMargin()
    height = panel.viewport().height() - 2 * document_margin
    return int(height // QFontMetrics(panel.document().defaultFont()).lineSpacing())


def at_end(panel) -> bool:
    bar = panel.verticalScrollBar()
    return bar.value() == bar.maximum()


def wheel_up(panel) -> None:
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtWidgets import QApplication

    viewport = panel.viewport()
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


# AC-09 ------------------------------------------------------------------------------------


@pytest.mark.parametrize(("size", "minimum"), [((1280, 720), 8), ((850, 560), 4)])
@pytest.mark.parametrize("running", [False, True], ids=["stopped", "running"])
def test_ac09_each_result_panel_shows_enough_transcript_lines(
    window, size, minimum, running
) -> None:
    if running:
        start(window)  # the session strip takes its row
        assert window.session_strip.isVisible()
    resize(window, *size)
    for panel in (window.source_text, window.target_text):
        assert panel.isVisible()
        assert visible_lines(panel) >= minimum, (size, visible_lines(panel))


def test_ac09_the_transcript_is_the_dominant_area(window) -> None:
    resize(window, 1280, 720)
    page = window.workspace_pages[window.current_workspace()]
    panel = window.source_panel
    assert panel.height() >= 0.6 * page.height()


# AC-10 ------------------------------------------------------------------------------------


def test_ac10_wheel_up_keeps_the_view_and_returning_to_the_end_follows_again(
    window,
    spies,  # noqa: F811
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    resize(window, 1280, 720)
    start(window)
    fill(window, spies, 14)
    panel = window.source_panel
    text = panel.text
    assert text.verticalScrollBar().maximum() > 0 and at_end(text) and panel.follow

    wheel_up(text)
    settle()
    assert not at_end(text) and not panel.follow
    kept = text.verticalScrollBar().value()
    submit(window, spies, transcript("Neuer Satz", "de"))
    assert wait_until(lambda: len(window.history) == 15)
    assert text.verticalScrollBar().value() == kept  # the view stays where the user left it
    assert at_end(window.target_text)  # the other panel still follows

    QTest.keyClick(text, Qt.Key.Key_End, Qt.KeyboardModifier.ControlModifier)
    settle()
    assert at_end(text) and panel.follow
    submit(window, spies, transcript("Noch ein Satz", "de"))
    assert wait_until(lambda: len(window.history) == 16)
    assert at_end(text)


@pytest.mark.parametrize(
    "key",
    ["Key_PageUp", "Key_Up", "Key_Home"],
)
def test_ac10_keyboard_scrolling_up_stops_following(window, spies, key) -> None:  # noqa: F811
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    resize(window, 1280, 720)
    start(window)
    fill(window, spies, 14)
    panel = window.source_panel
    text = panel.text
    modifier = Qt.KeyboardModifier.ControlModifier if key == "Key_Home" else None
    text.setFocus()
    # Up moves the caret; it starts at the end like a user who read to the last line.
    cursor = text.textCursor()
    cursor.movePosition(cursor.MoveOperation.End)
    text.setTextCursor(cursor)
    for _press in range(30 if key == "Key_Up" else 1):
        QTest.keyClick(text, getattr(Qt.Key, key), modifier or Qt.KeyboardModifier.NoModifier)
    settle()

    assert not at_end(text) and not panel.follow
    kept = text.verticalScrollBar().value()
    submit(window, spies, transcript("Neuer Satz", "de"))
    assert wait_until(lambda: len(window.history) == 15)
    assert text.verticalScrollBar().value() == kept


def test_ac10_scroll_bar_drag_up_stops_following(window, spies) -> None:  # noqa: F811
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    resize(window, 1280, 720)
    start(window)
    fill(window, spies, 14)
    panel = window.source_panel
    bar = panel.text.verticalScrollBar()
    QTest.mousePress(bar, Qt.MouseButton.LeftButton, pos=QPoint(bar.width() // 2, 3))
    QTest.mouseRelease(bar, Qt.MouseButton.LeftButton, pos=QPoint(bar.width() // 2, 3))
    settle()
    assert not at_end(panel.text) and not panel.follow


def test_ac10_programmatic_and_screen_reader_scrolling_never_stop_following(
    window,
    spies,  # noqa: F811
) -> None:
    resize(window, 1280, 720)
    start(window)
    fill(window, spies, 14)
    source, target = window.source_panel, window.target_panel
    source.text.verticalScrollBar().setValue(0)  # programmatic
    read_like_a_screen_reader(target.text)  # UI Automation selection and scroll-into-view
    settle()
    assert source.follow and target.follow

    submit(window, spies, transcript("Neuer Satz", "de"))
    assert wait_until(lambda: len(window.history) == 15)
    assert at_end(source.text) and at_end(target.text)
    assert target.text.textCursor().hasSelection()  # the reader's selection is kept


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
