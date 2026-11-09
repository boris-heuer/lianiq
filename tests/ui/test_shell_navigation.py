"""The shell navigation (CAP-0168 WI-02; spec §2.3.1, §2.3.3, §6.1).

pytest-qt style offscreen UI tests over spy adapters: AC-03 (sidebar order, Conversation
shown, removed controls), AC-04 (planned entries) and keyboard navigation (Up/Down, Enter,
Ctrl+1…6). AC-05, AC-08, the icon rail and the < 100 ms timing are in
``test_shell_navigation_workspaces.py``; the shared helpers in ``_navigation_helpers.py``.
The Native half of AC-03 is proven in WI-06.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from lianiq.ui.shell.navigation import WIDE_WIDTH
from lianiq.ui.shell.workspaces import DEFAULT_ENTRIES, WorkspaceId
from tests._spy_window import spies  # noqa: F401
from tests.ui._language_helpers import wait_until
from tests.ui._navigation_helpers import (
    PLANNED,
    activate,
    navigation_window,  # noqa: F401
    press,
    resize,
    texts_in,
)
from tests.ui.test_main_window_session import click
from tests.ui.test_main_window_wi08_fixes import (  # noqa: F401 - autouse Segoe UI fixture
    _load_windows_ui_font,
    use_windows_ui_font,
)

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
