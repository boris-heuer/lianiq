"""CAP-0172 WI-07: UIA names and keyboard operation of Text translation (AC-36, spec §2.3).

Every focusable control of the page has an accessible name (the UIA name) equal to its
visible label, also after **Translate** turns into **Cancel** and **Play translation** into
**Stop**; the Tab order is language row → source → result → action row. VoR-01..03 run from
the keyboard alone: Ctrl+3, typing, Enter on the focused **Translate**, Space on **Copy
translation** and **Play translation** (Stop), F9 from Settings. The native UIA read of the
same names is row E-13 (``native_e2e/rows/e13.py``).
"""

from __future__ import annotations

from lianiq.ui import strings
from lianiq.ui.shell.workspaces import WorkspaceId
from tests._spy_window import spies  # noqa: F401 - pytest fixture
from tests.ui._language_helpers import wait_until
from tests.ui._navigation_helpers import activate
from tests.ui.test_text_translation_playback import (  # noqa: F401 - pytest fixtures
    idle,
    page,
    player,
    playing,
    translated,
)

TAB_ORDER = [
    strings.TEXT_SOURCE_LANGUAGE,
    strings.TEXT_SWAP,
    strings.TEXT_TARGET_LANGUAGE,
    strings.TEXT_SOURCE_LABEL,
    strings.TEXT_COPY_SOURCE,
    strings.TEXT_RESULT_LABEL,
    strings.TEXT_COPY_TRANSLATION,
    strings.TEXT_EXPORT,
    strings.TEXT_TRANSLATE,
    strings.TEXT_PLAY,
]


def key(widget, name: str, modifier=None) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    keys = getattr(Qt.Key, f"Key_{name}")
    QTest.keyClick(widget, keys, modifier or Qt.KeyboardModifier.NoModifier)


def focus_widget():
    from PySide6.QtWidgets import QApplication

    QApplication.processEvents()
    return QApplication.focusWidget()


def named_controls(workspace) -> list:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QWidget

    return [
        widget
        for widget in workspace.page.findChildren(QWidget)
        if widget.focusPolicy() != Qt.FocusPolicy.NoFocus and widget.isVisibleTo(workspace.page)
    ]


def assert_named(workspace) -> None:
    from PySide6.QtWidgets import QPushButton

    for widget in named_controls(workspace):
        name = widget.accessibleName()
        assert name, type(widget).__name__
        if isinstance(widget, QPushButton):
            assert name == widget.text()


def test_ac36_every_control_is_named_after_its_label_in_each_state(page, player) -> None:  # noqa: F811
    assert_named(page)
    assert page.source_edit.accessibleName() == "Source text"
    assert page.result_edit.accessibleName() == "Translation"
    translated(page)
    assert_named(page)
    page.play_button.click()
    assert wait_until(playing(page))
    assert page.play_button.accessibleName() == strings.TEXT_STOP
    assert_named(page)
    page.play_button.click()
    assert wait_until(idle(page))
    assert page.play_button.accessibleName() == strings.TEXT_REPLAY
    page.source_edit.insertPlainText(" Neu.")
    assert strings.TEXT_STALE in page.result_edit.accessibleDescription()


def test_ac36_translate_reads_cancel_while_a_request_runs(page, spies) -> None:  # noqa: F811
    spies.release_warm_up.clear()  # the first request waits in the model warm-up
    page.source_edit.insertPlainText("Hallo.")
    page.translate_button.click()
    assert wait_until(lambda: page.translate_button.text() == strings.TEXT_CANCEL)
    assert page.translate_button.accessibleName() == strings.TEXT_CANCEL
    spies.release_warm_up.set()
    assert wait_until(lambda: page.translate_button.accessibleName() == strings.TEXT_TRANSLATE)


def test_ac36_tab_walks_language_row_source_result_and_action_row(page) -> None:  # noqa: F811
    translated(page)
    page.source_combo.setFocus()
    names = []
    for _ in TAB_ORDER:
        widget = focus_widget()
        names.append(widget.accessibleName())
        key(widget, "Tab")
    assert names == TAB_ORDER
    assert "\t" not in page.source_edit.toPlainText()  # Tab never lands in the draft


def test_ac36_vor01_to_vor03_run_from_the_keyboard(page, player) -> None:  # noqa: F811
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtTest import QTest

    window = page.host
    window.navigation.select(WorkspaceId.CONVERSATION)
    activate(window)
    key(focus_widget() or window, "3", Qt.KeyboardModifier.ControlModifier)
    assert window.current_workspace() is WorkspaceId.TEXT_TRANSLATION
    assert wait_until(lambda: focus_widget() is page.source_edit)
    QTest.keyClicks(page.source_edit, "Hallo. Welt.")  # typed
    page.translate_button.setFocus()
    key(page.translate_button, "Return")
    assert wait_until(lambda: page.controller.draft.current_result() is not None)
    page.copy_translation_button.setFocus()
    key(page.copy_translation_button, "Space")
    assert QGuiApplication.clipboard().text() == page.result_edit.toPlainText()
    page.play_button.setFocus()
    key(page.play_button, "Space")
    assert wait_until(playing(page))
    key(focus_widget(), "7", Qt.KeyboardModifier.ControlModifier)  # Settings
    assert window.current_workspace() is WorkspaceId.SETTINGS
    key(focus_widget() or window, "F9")
    assert wait_until(idle(page))
    assert page.source_edit.toPlainText() == "Hallo. Welt."
    key(focus_widget(), "3", Qt.KeyboardModifier.ControlModifier)
    page.swap_button.setFocus()
    key(page.swap_button, "Space")  # VoR-02: the other direction
    assert page.source_combo.currentText() == "Mandarin (Simplified)"
