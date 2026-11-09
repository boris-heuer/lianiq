"""Accessible names and focus after a held-turn resolve (CAP-0169 WI-10, WI-08 R5).

Native finding (R5 UI Automation Tab cycle with a held turn): the *Original* and
*Translation* panels and the *Model profile* combo were Tab stops without a name (DEF-04),
and after a keyboard resolve focus fell through the focus chain to that combo (DEF-05).
These offscreen tests read the same Qt accessibility interface Qt's UI Automation bridge
exposes; they are code evidence, the native Tab cycle is product evidence.

CAP-0168 AC-02: the widgets set their names and the focus return themselves, so a
``MainWindow`` built directly (as ``scripts/ui_self_test.py`` does) passes without any
post-construction step; ``ui/accessibility.py`` no longer exists (AC-01).

CAP-0168 WI-02: the model profile left the Conversation layout and is the read-only
*Model profile* value in Settings › Diagnostics (AC-12); it is still a named Tab stop there.
"""

from __future__ import annotations

import os
import threading

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from lianiq.languages import LanguageId
from tests._spy_window import build_window, spies  # noqa: F401
from tests.ui._language_helpers import press, start, submit, transcript, wait_until

DE = LanguageId("de")
# Each control's accessible name is the caption shown above it.
CONTROL_NAMES = {
    "input_combo": "Microphone",
    "output_combo": "Speakers",
    "model_profile_field": "Model profile",
    "source_text": "Original",
    "target_text": "Translation",
}


@pytest.fixture
def window(tmp_path, spies, monkeypatch):  # noqa: F811
    # Built directly: no accessibility step runs after construction (AC-02).
    window = build_window(tmp_path, monkeypatch)
    window.activateWindow()
    yield window
    window.stop_listening()
    window.close()


def accessible_name(widget) -> str:
    from PySide6.QtGui import QAccessible

    return QAccessible.queryAccessibleInterface(widget).text(QAccessible.Text.Name)


def tab_stops(window) -> list:
    """Every control the Tab key can reach now: enabled, visible, accepts Tab focus."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QWidget

    return [
        widget
        for widget in window.findChildren(QWidget)
        if widget.isEnabled()
        and widget.isVisible()
        and widget.focusPolicy() & Qt.FocusPolicy.TabFocus
        and widget.focusProxy() is None
    ]


def unnamed(window) -> list[str]:
    return [
        f"{type(widget).__name__}:{widget.objectName()}"
        for widget in tab_stops(window)
        if not accessible_name(widget).strip()
    ]


def focused():
    from PySide6.QtWidgets import QApplication

    return QApplication.focusWidget()


def gate_resolution(spies):  # noqa: F811
    """Block the re-recognition of a held turn until the returned event is set."""
    release = threading.Event()
    recognizer = spies.recognizer
    transcribe = recognizer.transcribe

    def gated(samples, sample_rate, language=None):
        if language is not None:
            assert release.wait(timeout=5.0)
        return transcribe(samples, sample_rate, language)

    recognizer.transcribe = gated
    return release


def test_ac02_def04_controls_are_named_after_their_visible_captions(window) -> None:
    for attribute, name in CONTROL_NAMES.items():
        assert accessible_name(getattr(window, attribute)) == name


def test_ac02_def04_every_tab_stop_has_an_accessible_name_stopped_and_with_a_held_turn(
    window,
    spies,  # noqa: F811
) -> None:
    assert tab_stops(window), "the window must have Tab stops"
    assert unnamed(window) == []

    start(window)
    submit(window, spies, transcript("It is a test.", "en"))
    assert wait_until(window.held_turn_bar.isVisible)
    stops = tab_stops(window)
    assert window.held_turn_bar.translate_buttons[DE] in stops
    assert window.source_text in stops
    assert unnamed(window) == []
    # The model profile is a named Tab stop on the Settings page (CAP-0168 AC-12).
    from lianiq.ui.shell.workspaces import WorkspaceId

    window.show_workspace(WorkspaceId.SETTINGS)
    assert window.model_profile_field in tab_stops(window)
    assert unnamed(window) == []
    window.show_workspace(WorkspaceId.CONVERSATION)


def test_def05_focus_stays_in_the_bar_while_resolving_then_moves_to_the_next_turn_and_stop(
    window,
    spies,  # noqa: F811
) -> None:
    from PySide6.QtCore import Qt

    start(window)
    bar = window.held_turn_bar
    submit(window, spies, transcript("First unclear turn", "en"))
    assert wait_until(bar.isVisible)
    submit(window, spies, transcript("Second unclear turn", "en"))
    assert wait_until(bar.counter_label.isVisible)

    release = gate_resolution(spies)
    spies.recognizer.results.append(transcript("Erster Satz", "de"))
    german = bar.translate_buttons[DE]
    german.setFocus()
    assert wait_until(lambda: focused() is german)
    press(german, Qt.Key.Key_Space)
    assert bar.resolving
    assert focused() is bar  # parked on the bar, named "Language unclear — …"
    assert accessible_name(bar)
    release.set()

    assert wait_until(lambda: not bar.resolving and bar.excerpt == "“Second unclear turn”")
    assert wait_until(lambda: focused() is german)  # the next held turn's first button

    spies.recognizer.results.append(transcript("Zweiter Satz", "de"))
    press(german, Qt.Key.Key_Space)
    assert wait_until(lambda: len(window.history) == 2 and not bar.isVisible())
    assert wait_until(lambda: focused() is window.stop_button)
    assert focused() is not window.model_profile_field


def test_def05_stop_with_focus_in_the_bar_moves_focus_to_start(window, spies) -> None:  # noqa: F811
    start(window)
    bar = window.held_turn_bar
    submit(window, spies, transcript("It is a test.", "en"))
    assert wait_until(bar.isVisible)
    bar.discard_button.setFocus()
    assert wait_until(lambda: focused() is bar.discard_button)

    window.stop_listening()  # what F9 does

    assert not bar.isVisible()
    assert wait_until(lambda: focused() is window.start_button)


def test_def05_discard_of_the_last_turn_moves_focus_to_stop(window, spies) -> None:  # noqa: F811
    from PySide6.QtCore import Qt

    start(window)
    bar = window.held_turn_bar
    submit(window, spies, transcript("It is a test.", "en"))
    assert wait_until(bar.isVisible)
    bar.discard_button.setFocus()
    assert wait_until(lambda: focused() is bar.discard_button)

    press(bar.discard_button, Qt.Key.Key_Space)

    assert not bar.isVisible()
    assert wait_until(lambda: focused() is window.stop_button)


def activate_other_window():
    """Show and activate a second top-level window, so the main window is inactive."""
    from PySide6.QtWidgets import QApplication, QWidget

    other = QWidget()
    other.show()
    other.activateWindow()
    assert wait_until(lambda: QApplication.activeWindow() is other)
    return other


def test_def05_focus_is_returned_while_the_window_is_inactive(window, spies) -> None:  # noqa: F811
    start(window)
    bar = window.held_turn_bar
    submit(window, spies, transcript("It is a test.", "en"))
    assert wait_until(bar.isVisible)
    bar.discard_button.setFocus()
    assert wait_until(lambda: focused() is bar.discard_button)
    other = activate_other_window()
    try:
        assert focused() is not bar.discard_button
        assert window.focusWidget() is bar.discard_button  # restored on reactivation

        window.stop_listening()

        assert wait_until(lambda: window.focusWidget() is window.start_button)
    finally:
        other.close()


def test_def05_focus_moves_to_the_next_turn_while_the_window_is_inactive(
    window,
    spies,  # noqa: F811
) -> None:
    from PySide6.QtCore import Qt

    start(window)
    bar = window.held_turn_bar
    submit(window, spies, transcript("First unclear turn", "en"))
    assert wait_until(bar.isVisible)
    submit(window, spies, transcript("Second unclear turn", "en"))
    assert wait_until(bar.counter_label.isVisible)
    release = gate_resolution(spies)
    spies.recognizer.results.append(transcript("Erster Satz", "de"))
    german = bar.translate_buttons[DE]
    german.setFocus()
    assert wait_until(lambda: focused() is german)
    press(german, Qt.Key.Key_Space)
    assert window.focusWidget() is bar
    other = activate_other_window()
    try:
        release.set()
        assert wait_until(lambda: not bar.resolving and bar.excerpt == "“Second unclear turn”")
        assert wait_until(lambda: window.focusWidget() is german)
    finally:
        other.close()
