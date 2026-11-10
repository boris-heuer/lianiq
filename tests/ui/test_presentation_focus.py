"""AC-28 (UI AND UIA): Tab order, focus outline, Ctrl+1…6 and focus return (CAP-0168 WI-05).

UI: Tab runs sidebar → workspace → session strip and wraps; Shift+Tab goes back; every
focused Tab stop draws the 2 px focus outline (read from the rendered pixels); Ctrl+1…6
select the enabled entries; focus returns to the invoking control after the export dialogs
and after switching back to a workspace. UIA: the same Tab stops through Qt's accessibility
interface (what the UI Automation bridge reads): focused state, a name, and the window's
focus child. Offscreen code evidence; Narrator on Windows is WI-06 (AC-30).
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from lianiq.ui import notice_catalog as catalog
from lianiq.ui import theme
from lianiq.ui.shell.workspaces import WorkspaceId
from tests._spy_window import build_window, spies  # noqa: F401
from tests.ui._language_helpers import start, submit, transcript, wait_until
from tests.ui._navigation_helpers import activate, press
from tests.ui.test_main_window_accessibility import accessible_name, focused, tab_stops

CONVERSATION, CALL_BRIDGE, SETTINGS = (
    WorkspaceId.CONVERSATION,
    WorkspaceId.CALL_BRIDGE,
    WorkspaceId.SETTINGS,
)


@pytest.fixture
def window(tmp_path, spies, monkeypatch):  # noqa: F811
    window = build_window(tmp_path, monkeypatch)
    theme.apply(window, high_contrast=False)  # the stylesheet, whatever the build machine
    activate(window)
    yield window
    window.stop_listening()
    window.close()


def region(window, widget) -> int:
    for index, area in enumerate(window.focus_regions()):
        if area.isAncestorOf(widget):
            return index
    raise AssertionError(f"{widget!r} is outside the sidebar, the workspace and the strip")


def outline_shown(widget) -> bool:
    """The focus colour is drawn on the widget's border (2 px, mid-points of each edge)."""
    from PySide6.QtGui import QColor

    image = widget.grab().toImage()
    ratio = image.devicePixelRatio()
    width, height = image.width(), image.height()
    focus = QColor(theme.COLORS["focus"])
    inset = range(int(theme.FOCUS_WIDTH * ratio))
    points = [(width // 2, d) for d in inset] + [(width // 2, height - 1 - d) for d in inset]
    points += [(d, height // 2) for d in inset] + [(width - 1 - d, height // 2) for d in inset]
    for x, y in points:
        color = image.pixelColor(x, y)
        channels = zip(color.getRgb()[:3], focus.getRgb()[:3], strict=True)
        if max(abs(drawn - expected) for drawn, expected in channels) <= 24:
            return True
    return False


def uia_focused(window, widget) -> bool:
    from PySide6.QtGui import QAccessible

    interface = QAccessible.queryAccessibleInterface(widget)
    return interface.state().focused and bool(accessible_name(widget).strip())


def tab_cycle(window, key_modifier=None) -> list:
    from PySide6.QtCore import Qt

    visited = []
    for _ in range(len(tab_stops(window))):  # once round: back where it started
        key = Qt.Key.Key_Backtab if key_modifier else Qt.Key.Key_Tab
        press(focused(), key, key_modifier)
        visited.append(focused())
    return visited


@pytest.mark.parametrize("running", [True, False], ids=["running", "stopped"])
@pytest.mark.parametrize("workspace", [CONVERSATION, CALL_BRIDGE, SETTINGS])
def test_ac28_tab_runs_sidebar_workspace_strip_with_outline_and_names(
    window, workspace, running
) -> None:
    if running:
        start(window)  # the strip and its Stop are shown while a session runs
    window.show_workspace(workspace)
    # A notice action created now still belongs to its workspace, not behind the strip.
    window.post_notice(catalog.start_failed(workspace, "test", catalog.source(workspace), str))
    first = window.navigation.buttons[CONVERSATION]
    first.setFocus()
    assert wait_until(lambda: focused() is first)
    stops = tab_stops(window)

    visited = [first, *tab_cycle(window)]

    cycle = visited[:-1]
    assert set(cycle) == set(stops) and len(cycle) == len(stops)
    regions = [region(window, widget) for widget in cycle]
    # While stopped the strip is hidden, so the workspace's last control ends the round.
    assert regions == sorted(regions) and set(regions) == ({0, 1, 2} if running else {0, 1}), (
        regions
    )
    assert (cycle[-1] is window.stop_button) is running and visited[-1] is first  # wraps
    from PySide6.QtCore import Qt

    backwards = tab_cycle(window, Qt.KeyboardModifier.ShiftModifier)
    assert backwards[0] is cycle[-1] and backwards[-1] is first
    assert [first, *reversed(backwards[:-1])] == cycle
    for widget in stops:
        widget.setFocus(Qt.FocusReason.TabFocusReason)
        assert focused() is widget
        assert outline_shown(widget), f"{type(widget).__name__} {accessible_name(widget)!r}"
        assert uia_focused(window, widget), accessible_name(widget)


def test_ac28_the_window_reports_the_focused_control_to_ui_automation(window) -> None:
    from PySide6.QtGui import QAccessible

    window.start_button.setFocus()
    assert wait_until(lambda: focused() is window.start_button)
    child = QAccessible.queryAccessibleInterface(window).focusChild()
    assert child is not None and child.object() is window.start_button
    assert child.text(QAccessible.Text.Name) == "▶  Start  (F8)"


def test_ac28_focus_outline_is_the_native_one_in_high_contrast(window) -> None:
    theme.apply(window, high_contrast=True)
    assert window.styleSheet() == "" and window.property("highContrast") is True
    theme.apply(window, high_contrast=False)
    assert "QPushButton:focus" in window.styleSheet()


def test_ac28_ctrl_number_and_focus_returns_after_switching_back(window) -> None:
    from PySide6.QtCore import Qt

    control = Qt.KeyboardModifier.ControlModifier
    window.swap_button.setFocus()
    assert wait_until(lambda: focused() is window.swap_button)
    press(focused(), Qt.Key.Key_6, control)
    assert window.current_workspace() is SETTINGS
    settings_value = window.model_profile_field
    settings_value.setFocus()
    press(focused(), Qt.Key.Key_4, control)
    assert window.current_workspace() is CALL_BRIDGE
    press(focused(), Qt.Key.Key_2, control)  # planned: ignored
    assert window.current_workspace() is CALL_BRIDGE

    press(focused(), Qt.Key.Key_1, control)
    assert window.current_workspace() is CONVERSATION
    assert focused() is window.swap_button  # the control that invoked the switch
    press(focused(), Qt.Key.Key_6, control)
    assert focused() is settings_value

    # Switching from the sidebar keeps focus in the sidebar.
    entry = window.navigation.buttons[CONVERSATION]
    entry.setFocus()
    press(entry, Qt.Key.Key_Return)
    assert window.current_workspace() is CONVERSATION and focused() is entry


def test_ac28_focus_returns_to_export_transcript_after_its_dialogs(window, spies, monkeypatch):  # noqa: F811
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    button = window.conversation.export_button
    shown = []
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a: shown.append(a)))
    button.setFocus()
    window.statusBar().setFocus()  # the dialog took focus away
    button.click()
    assert shown and focused() is button

    start(window)
    submit(window, spies, transcript("Guten Tag", "de"))
    assert wait_until(lambda: len(window.history) == 1)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *_a: ("", "")))
    window.source_text.setFocus()
    button.click()
    assert focused() is button
