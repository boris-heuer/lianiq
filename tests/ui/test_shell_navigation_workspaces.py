"""Shell workspaces: Call Bridge page, navigation state, icon rail, timing (CAP-0168 WI-02).

Split from ``test_shell_navigation.py`` (spec §2.3.1, §2.3.3, §6.1): AC-05 (Call Bridge
page), AC-08 (navigating away and back changes nothing), the icon rail below 1000 px and the
< 100 ms navigation timing (§6.1, Should), over the seven entries of CAP-0177 (Meeting
second). The shared helpers are in ``_navigation_helpers.py``.
"""

from __future__ import annotations

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from lianiq.ui.shell.navigation import RAIL_WIDTH, WIDE_WIDTH
from lianiq.ui.shell.workspaces import DEFAULT_ENTRIES, WorkspaceId
from tests._spy_window import spies  # noqa: F401
from tests.ui import _conversation_helpers as conv
from tests.ui._language_helpers import start
from tests.ui._navigation_helpers import (
    ENABLED,
    fill,
    navigation_window,  # noqa: F401
    resize,
)
from tests.ui.test_main_window_session import click
from tests.ui.test_main_window_wi08_fixes import (  # noqa: F401 - autouse Segoe UI fixture
    _load_windows_ui_font,
)

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
        assert items[0] == "Select a device …" and combo.itemData(0) is None
        assert not any("default" in item.lower() for item in items)


# AC-08 ------------------------------------------------------------------------------------


def settled_synthesis(window, spy_set, turns: int) -> int:
    """The synthesis count once every filled turn is spoken and the output is idle.

    Waits for the expected call count itself: a count that is only stable for a moment can
    still be one short while the last turn is queued on the synthesis thread.
    """
    from PySide6.QtTest import QTest

    from lianiq.conversation.spoken_output import PlaybackState

    def count() -> int:
        return len(spy_set.synthesizer.calls) if spy_set.synthesizer else 0

    spoken = getattr(window.pipeline, "spoken", None)
    expected = turns if spy_set.synthesizer else 0
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        idle = spoken is None or spoken.state is PlaybackState.IDLE
        if idle and count() >= expected:
            break
        QTest.qWait(50)
    QTest.qWait(200)  # nothing more may follow the last turn
    return count()


def test_ac08_navigating_away_and_back_keeps_turns_scroll_selection_and_pair(
    window,
    spies,  # noqa: F811
    monkeypatch,
) -> None:
    window.mode_combo.setCurrentText("German → Mandarin (Simplified)")
    resize(window, 1280, 720)
    start(window)
    fill(window, spies, 12)
    view = window.conversation.paired_view
    bar = view.list.verticalScrollBar()
    assert bar.maximum() > 0
    bar.setValue(bar.maximum() // 2)
    view.select_row(3)
    calls = []
    spoken = settled_synthesis(window, spies, 12)  # the 12 turns, spoken after their text
    assert spoken == (12 if spies.synthesizer else 0)
    capture = window.capture
    monkeypatch.setattr(capture, "start", lambda: calls.append("start"))
    monkeypatch.setattr(capture, "stop", lambda: calls.append("stop"))
    before = (
        conv.originals(window),
        conv.translations(window),
        bar.value(),
        view.current_turn(),
        window.pair_combo.currentText(),
        window.mode_combo.currentText(),
        len(window.history),
    )

    workspaces = (WorkspaceId.SETTINGS, WorkspaceId.MEETING, WorkspaceId.CALL_BRIDGE)
    for workspace in (*workspaces, WorkspaceId.CONVERSATION):
        click(window.navigation.buttons[workspace])
        assert window.current_workspace() is workspace

    after = (
        conv.originals(window),
        conv.translations(window),
        bar.value(),
        view.current_turn(),
        window.pair_combo.currentText(),
        window.mode_combo.currentText(),
        len(window.history),
    )
    assert after == before
    assert calls == []  # no capture started or stopped
    assert window.capture.running and window.session_controller.running
    assert (len(spies.synthesizer.calls) if spies.synthesizer else 0) == spoken  # no playback


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
