"""The shell navigation (CAP-0168 WI-02; spec §2.3.1, §2.3.3, §6.1).

pytest-qt style offscreen UI tests over spy adapters: AC-03 (sidebar order, Conversation
shown, removed controls), AC-04 (planned entries), AC-05 (Call Bridge page), AC-08
(navigating away and back changes nothing), the icon rail below 1000 px, keyboard
navigation (Up/Down, Enter, Ctrl+1…6) and the < 100 ms navigation timing (§6.1, Should).
The Native half of AC-03 is proven in WI-06.
"""

from __future__ import annotations

import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from lianiq.ui.shell.navigation import RAIL_WIDTH, WIDE_WIDTH
from lianiq.ui.shell.workspaces import DEFAULT_ENTRIES, WorkspaceId
from tests.test_requirement_scoped_loading import build_window, spies  # noqa: F401
from tests.ui.test_main_window_languages import start, submit, transcript, wait_until
from tests.ui.test_main_window_session import click
from tests.ui.test_main_window_wi08_fixes import (  # noqa: F401 - autouse Segoe UI fixture
    _load_windows_ui_font,
    use_windows_ui_font,
)

PLANNED = (WorkspaceId.TEXT_TRANSLATION, WorkspaceId.LISTEN, WorkspaceId.LANGUAGE_PACKS)
ENABLED = (WorkspaceId.CONVERSATION, WorkspaceId.CALL_BRIDGE, WorkspaceId.SETTINGS)


@pytest.fixture
def window(tmp_path, spies, monkeypatch):  # noqa: F811
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


def fill(window, spies, turns: int) -> None:  # noqa: F811
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


# AC-03 ------------------------------------------------------------------------------------


def test_ac03_sidebar_lists_six_entries_in_order_with_settings_at_the_bottom(window) -> None:
    navigation = window.navigation
    buttons = [navigation.buttons[item.id] for item in DEFAULT_ENTRIES]
    assert [button.accessibleName() for button in buttons] == [
        "Conversation",
        "Text translation",
        "Listen & translate",
        "Call Bridge",
        "Language packs",
        "Settings",
    ]
    tops = [button.geometry().top() for button in buttons]
    assert tops == sorted(tops)  # top to bottom in registry order
    settings = navigation.buttons[WorkspaceId.SETTINGS]
    packs = navigation.buttons[WorkspaceId.LANGUAGE_PACKS]
    # Settings is bottom-aligned: a stretch separates it from the other entries.
    assert settings.geometry().top() - packs.geometry().bottom() > 100
    assert navigation.height() - settings.geometry().bottom() <= 20
    # Never top tabs: the sidebar is a vertical strip on the left.
    assert navigation.geometry().left() == 0 and navigation.height() > navigation.width()


def test_entry_labels_show_a_literal_ampersand_and_carry_no_mnemonic(window) -> None:
    from PySide6.QtGui import QKeySequence

    for item in DEFAULT_ENTRIES:
        button = window.navigation.buttons[item.id]
        assert QKeySequence.mnemonic(button.text()).isEmpty(), button.text()
        assert button.shortcut().isEmpty()
    listen = window.navigation.buttons[WorkspaceId.LISTEN].text()
    # What Qt draws: "&&" renders as one "&", so the visible label matches the spoken name.
    assert listen.replace("&&", "&").startswith("Listen & translate")


def test_ac03_conversation_is_shown_without_bridge_profile_cuda_or_subtitle(window) -> None:
    from lianiq.ui.call_bridge_panel import CallBridgePanel

    assert window.current_workspace() is WorkspaceId.CONVERSATION
    assert window.navigation.current() is WorkspaceId.CONVERSATION
    assert window.navigation.buttons[WorkspaceId.CONVERSATION].isChecked()
    page = window.workspace_pages[WorkspaceId.CONVERSATION]
    assert page.isVisible()
    assert page.findChildren(CallBridgePanel) == []
    assert not window.call_bridge_panel.isVisible()
    page_texts = texts_in(page)
    for removed in ("Model profile", "CUDA GPU", "Balanced · Whisper small + MarianMT"):
        assert removed not in page_texts
    assert not any("Ryzen" in text or "Local · Private" in text for text in texts_in(window))
    assert not any("CUDA GPU" in text for text in texts_in(window))


def test_wide_sidebar_labels_are_not_clipped(window) -> None:
    use_windows_ui_font(window)  # widths need the Windows UI font (see WI-08 DEV-01)
    resize(window, 1280, 720)
    assert window.navigation.width() >= WIDE_WIDTH
    for button in window.navigation.buttons.values():
        assert button.width() >= button.sizeHint().width(), button.accessibleName()


# AC-04 ------------------------------------------------------------------------------------


@pytest.mark.parametrize("workspace", PLANNED)
def test_ac04_a_planned_entry_never_changes_the_page(window, workspace) -> None:
    from PySide6.QtCore import Qt

    button = window.navigation.buttons[workspace]
    assert not button.isEnabled()
    assert button.accessibleDescription() == "Planned — not available yet"
    assert button.toolTip() == "Planned — not available yet"
    assert button.text().endswith("Planned")

    click(button)
    press(button, Qt.Key.Key_Space)
    press(button, Qt.Key.Key_Return)
    assert not window.navigation.select(workspace)
    assert not window.show_workspace(workspace)
    index = [item.id for item in DEFAULT_ENTRIES].index(workspace)
    activate(window)
    press(
        window.focusWidget() or window,
        getattr(Qt.Key, f"Key_{index + 1}"),
        Qt.KeyboardModifier.ControlModifier,
    )

    assert window.current_workspace() is WorkspaceId.CONVERSATION
    assert window.navigation.current() is WorkspaceId.CONVERSATION


def test_ac04_up_down_skip_planned_entries_and_enter_selects(window) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    buttons = window.navigation.buttons
    activate(window)
    buttons[WorkspaceId.CONVERSATION].setFocus()
    assert wait_until(lambda: QApplication.focusWidget() is buttons[WorkspaceId.CONVERSATION])

    press(buttons[WorkspaceId.CONVERSATION], Qt.Key.Key_Down)
    assert QApplication.focusWidget() is buttons[WorkspaceId.CALL_BRIDGE]
    assert window.current_workspace() is WorkspaceId.CONVERSATION  # moving does not select
    press(buttons[WorkspaceId.CALL_BRIDGE], Qt.Key.Key_Down)
    assert QApplication.focusWidget() is buttons[WorkspaceId.SETTINGS]
    press(buttons[WorkspaceId.SETTINGS], Qt.Key.Key_Down)  # no wrap-around
    assert QApplication.focusWidget() is buttons[WorkspaceId.SETTINGS]
    press(buttons[WorkspaceId.SETTINGS], Qt.Key.Key_Return)
    assert window.current_workspace() is WorkspaceId.SETTINGS
    press(buttons[WorkspaceId.SETTINGS], Qt.Key.Key_Up)
    assert QApplication.focusWidget() is buttons[WorkspaceId.CALL_BRIDGE]
    press(buttons[WorkspaceId.CALL_BRIDGE], Qt.Key.Key_Space)
    assert window.current_workspace() is WorkspaceId.CALL_BRIDGE
    assert buttons[WorkspaceId.CALL_BRIDGE].isChecked()
    assert not buttons[WorkspaceId.SETTINGS].isChecked()


def test_ctrl_number_selects_enabled_entries(window) -> None:
    from PySide6.QtCore import Qt

    activate(window)
    control = Qt.KeyboardModifier.ControlModifier
    for key, expected in (
        (Qt.Key.Key_6, WorkspaceId.SETTINGS),
        (Qt.Key.Key_4, WorkspaceId.CALL_BRIDGE),
        (Qt.Key.Key_2, WorkspaceId.CALL_BRIDGE),  # planned: ignored
        (Qt.Key.Key_1, WorkspaceId.CONVERSATION),
    ):
        press(window.focusWidget() or window, key, control)
        assert window.current_workspace() is expected


# AC-05 ------------------------------------------------------------------------------------


def test_ac05_call_bridge_is_experimental_with_explicit_endpoint_selectors_only(window) -> None:
    from PySide6.QtWidgets import QComboBox

    button = window.navigation.buttons[WorkspaceId.CALL_BRIDGE]
    assert button.isEnabled()
    assert button.text() == "Call Bridge\nExperimental"
    assert button.accessibleName() == "Call Bridge"
    assert button.accessibleDescription() == "Experimental"

    click(button)

    page = window.workspace_pages[WorkspaceId.CALL_BRIDGE]
    panel = window.call_bridge_panel
    assert window.current_workspace() is WorkspaceId.CALL_BRIDGE
    assert page.isVisible() and panel.isVisible() and page.isAncestorOf(panel)
    combos = page.findChildren(QComboBox)
    assert sorted(map(id, combos)) == sorted(map(id, panel.endpoint_combos.values()))
    for combo in combos:
        items = [combo.itemText(i) for i in range(combo.count())]
        assert items[0] == "Select an endpoint …" and combo.itemData(0) is None
        assert not any("default" in item.lower() for item in items)


# AC-08 ------------------------------------------------------------------------------------


def test_ac08_navigating_away_and_back_keeps_turns_scroll_selection_and_pair(
    window,
    spies,  # noqa: F811
    monkeypatch,
) -> None:
    from PySide6.QtGui import QTextCursor

    window.mode_combo.setCurrentText("German → Mandarin (Simplified)")
    resize(window, 1280, 720)
    start(window)
    fill(window, spies, 12)
    source = window.source_text
    bar = source.verticalScrollBar()
    assert bar.maximum() > 0
    bar.setValue(bar.maximum() // 2)
    cursor = source.textCursor()
    cursor.setPosition(3)
    cursor.setPosition(12, QTextCursor.MoveMode.KeepAnchor)
    source.setTextCursor(cursor)
    calls = []
    capture = window.capture
    monkeypatch.setattr(capture, "start", lambda: calls.append("start"))
    monkeypatch.setattr(capture, "stop", lambda: calls.append("stop"))
    before = (
        window.source_text.toPlainText(),
        window.target_text.toPlainText(),
        bar.value(),
        window.target_text.verticalScrollBar().value(),
        (source.textCursor().anchor(), source.textCursor().position()),
        window.pair_combo.currentText(),
        window.mode_combo.currentText(),
        len(window.history),
    )

    for workspace in (WorkspaceId.SETTINGS, WorkspaceId.CALL_BRIDGE, WorkspaceId.CONVERSATION):
        click(window.navigation.buttons[workspace])
        assert window.current_workspace() is workspace

    after = (
        window.source_text.toPlainText(),
        window.target_text.toPlainText(),
        bar.value(),
        window.target_text.verticalScrollBar().value(),
        (source.textCursor().anchor(), source.textCursor().position()),
        window.pair_combo.currentText(),
        window.mode_combo.currentText(),
        len(window.history),
    )
    assert after == before
    assert calls == []  # no capture started or stopped
    assert window.capture.running and window.session_controller.running
    assert spies.synthesizer is None or spies.synthesizer.calls == []  # no playback


# Icon rail --------------------------------------------------------------------------------


def test_below_1000_px_the_sidebar_is_an_icon_rail_with_unchanged_names(window) -> None:
    from PySide6.QtCore import Qt

    navigation = window.navigation
    names = {key: button.accessibleName() for key, button in navigation.buttons.items()}
    resize(window, 999, 700)
    assert navigation.compact and navigation.width() == RAIL_WIDTH
    for item in DEFAULT_ENTRIES:
        button = navigation.buttons[item.id]
        assert button.toolButtonStyle() is Qt.ToolButtonStyle.ToolButtonIconOnly
        assert button.accessibleName() == names[item.id]
        assert item.label in button.toolTip()  # the label moved to the tooltip
        assert button.sizeHint().width() <= button.width() <= RAIL_WIDTH
    resize(window, 850, 560)
    assert navigation.compact
    resize(window, 1000, 700)
    assert not navigation.compact and navigation.width() >= WIDE_WIDTH
    assert {key: button.accessibleName() for key, button in navigation.buttons.items()} == names


# Spec §6.1: navigation < 100 ms ----------------------------------------------------------


def test_navigation_between_workspaces_takes_less_than_100_ms(window, spies) -> None:  # noqa: F811
    from PySide6.QtWidgets import QApplication

    start(window)
    fill(window, spies, 10)
    timings = []
    for _cycle in range(3):
        for workspace in (*ENABLED[1:], ENABLED[0]):
            started = time.perf_counter()
            click(window.navigation.buttons[workspace])
            QApplication.processEvents()
            timings.append(time.perf_counter() - started)
            assert window.current_workspace() is workspace
    assert max(timings) < 0.1, timings
