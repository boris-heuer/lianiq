"""The session strip and the one active session across modes (CAP-0168 WI-02; spec §2.3.2).

pytest-qt style offscreen UI tests: AC-06 (the strip with **Stop (F9)** in every enabled
workspace; Stop and F9 from Settings stop the session) and the UI half of AC-07 (a second
session is refused in both directions and opens no stream). The Unit half of AC-07 is in
``test_shell_session_owner.py``; the Native half of AC-06 is proven in WI-06.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from lianiq.ui.shell.session_owner import SessionBusy, SessionState
from lianiq.ui.shell.workspaces import WorkspaceId
from tests._spy_window import build_window, spies  # noqa: F401
from tests.ui._call_bridge_window import (
    FakeCaptureStream,
    assign,
    build_call_bridge_window,
)
from tests.ui._language_helpers import start, submit, transcript, wait_until
from tests.ui.test_main_window_session import click

ENABLED = (WorkspaceId.CONVERSATION, WorkspaceId.CALL_BRIDGE, WorkspaceId.SETTINGS)
CONVERSATION_BUSY = "Stop the Conversation session first"
CALL_BRIDGE_BUSY = "Stop the Call Bridge session first"


@pytest.fixture
def window(tmp_path, spies, monkeypatch):  # noqa: F811
    window = build_call_bridge_window(tmp_path, monkeypatch)
    yield window
    window.stop_call_bridge()
    window.stop_listening()
    window.close()


def strip_shows(window, text: str) -> bool:
    strip = window.session_strip
    return strip.isVisible() and strip.state_label.text() == text


def test_the_strip_is_hidden_and_stop_disabled_while_idle(window) -> None:
    assert not window.session_strip.isVisible()
    assert not window.stop_button.isEnabled()
    assert window.session_owner.state is SessionState.IDLE
    assert window.stop_button.text() == "Stop (F9)"
    assert window.stop_button.accessibleName() == "Stop (F9)"


def test_ac06_the_strip_with_stop_is_visible_in_every_enabled_workspace(window, spies) -> None:  # noqa: F811
    start(window)
    submit(window, spies, transcript("Guten Tag", "de"))
    assert wait_until(lambda: len(window.history) == 1)
    assert window.session_owner.state is SessionState.RUNNING
    marker = window.navigation.buttons[WorkspaceId.CONVERSATION]

    for workspace in (*ENABLED[1:], ENABLED[0]):
        click(window.navigation.buttons[workspace])
        assert window.current_workspace() is workspace
        assert strip_shows(window, "Conversation running")
        assert window.stop_button.isVisible() and window.stop_button.isEnabled()
        assert marker.text().endswith("●")
        assert "Session running" in marker.accessibleDescription()


def test_ac06_stop_in_the_strip_stops_the_session_from_settings(window, spies) -> None:  # noqa: F811
    start(window)
    submit(window, spies, transcript("Guten Tag", "de"))
    assert wait_until(lambda: len(window.history) == 1)
    click(window.navigation.buttons[WorkspaceId.SETTINGS])

    click(window.stop_button)

    assert not window.capture.running and not window.session_controller.running
    assert window.session_owner.state is SessionState.IDLE
    assert not window.session_strip.isVisible()
    assert window.current_workspace() is WorkspaceId.SETTINGS  # Stop never navigates
    assert window.source_text.toPlainText().strip() == "German: Guten Tag"  # transcript kept
    assert not window.navigation.buttons[WorkspaceId.CONVERSATION].text().endswith("●")


def test_ac06_f9_from_settings_stops_the_session(window) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    start(window)
    click(window.navigation.buttons[WorkspaceId.SETTINGS])
    window.activateWindow()
    assert wait_until(lambda: QApplication.activeWindow() is window)
    field = window.model_profile_field
    field.setFocus()
    assert wait_until(lambda: QApplication.focusWidget() is field)

    QTest.keyClick(field, Qt.Key.Key_F9)

    assert wait_until(lambda: not window.capture.running)
    assert window.session_owner.state is SessionState.IDLE
    assert window.current_workspace() is WorkspaceId.SETTINGS


def test_stop_while_models_load_cancels_the_start(window, spies) -> None:  # noqa: F811
    spies.release_warm_up.clear()
    click(window.start_button)
    assert strip_shows(window, "Conversation starting…")
    assert window.stop_button.isEnabled()

    click(window.stop_button)
    spies.release_warm_up.set()

    assert window.session_owner.state is SessionState.IDLE
    assert not window.session_strip.isVisible()
    assert not wait_until(lambda: window.capture.running, timeout_ms=300)


def test_ac07_call_bridge_start_is_refused_while_the_conversation_runs(window) -> None:
    panel = window.call_bridge_panel
    assign(window)
    assert panel.start_button.isEnabled() and panel.start_button.toolTip() == ""
    start(window)

    assert not panel.start_button.isEnabled()
    assert panel.start_button.toolTip() == CONVERSATION_BUSY
    click(window.navigation.buttons[WorkspaceId.CALL_BRIDGE])
    click(panel.start_button)  # disabled: nothing happens
    window.start_call_bridge()  # a programmatic request is refused with the same text

    notice = window.notices.top(WorkspaceId.CALL_BRIDGE)  # an info notice (CAP-0168 WI-03)
    assert notice.title == CONVERSATION_BUSY and notice.severity.name == "INFO"
    assert FakeCaptureStream.instances == []  # no stream opened
    assert window.call_bridge_controller is None and not window.call_bridge.starting
    assert window.capture.running and window.session_controller.running
    with pytest.raises(SessionBusy):
        window.session_owner.request_start(WorkspaceId.CALL_BRIDGE)

    window.stop_listening()
    assert panel.start_button.isEnabled() and panel.start_button.toolTip() == ""


def test_ac07_conversation_start_is_refused_while_the_call_bridge_runs(window) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    assign(window)
    click(window.call_bridge_panel.start_button)
    assert wait_until(lambda: window.call_bridge_controller is not None)
    assert strip_shows(window, "Call Bridge running")
    streams = list(FakeCaptureStream.instances)

    assert not window.start_button.isEnabled()
    assert window.start_button.toolTip() == CALL_BRIDGE_BUSY
    window.start_listening()  # F8 / programmatic
    QTest.keyClick(window, Qt.Key.Key_F8)

    notice = window.conversation_notice()
    assert notice.title == CALL_BRIDGE_BUSY and notice.severity.name == "INFO"
    assert not window.capture.running and not window.conversation.starting
    assert FakeCaptureStream.instances == streams
    assert window.call_bridge_controller is not None
    with pytest.raises(SessionBusy):
        window.session_owner.request_start(WorkspaceId.CONVERSATION)

    click(window.navigation.buttons[WorkspaceId.SETTINGS])
    click(window.stop_button)  # the strip stops the Call Bridge too

    assert window.call_bridge_controller is None
    assert window.session_owner.state is SessionState.IDLE
    assert window.start_button.isEnabled() and window.start_button.toolTip() == ""


def test_f9_from_settings_stops_a_running_call_bridge(window) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    assign(window)
    click(window.call_bridge_panel.start_button)
    assert wait_until(lambda: window.call_bridge_controller is not None)
    assert window.session_owner.active is WorkspaceId.CALL_BRIDGE
    click(window.navigation.buttons[WorkspaceId.SETTINGS])
    window.activateWindow()
    assert wait_until(lambda: QApplication.activeWindow() is window)
    field = window.model_profile_field
    field.setFocus()
    assert wait_until(lambda: QApplication.focusWidget() is field)

    QTest.keyClick(field, Qt.Key.Key_F9)

    assert wait_until(lambda: window.call_bridge_controller is None)
    assert window.session_owner.state is SessionState.IDLE
    assert window.session_owner.active is None
    assert window.current_workspace() is WorkspaceId.SETTINGS


def test_opening_workspaces_never_starts_a_session(tmp_path, spies, monkeypatch) -> None:  # noqa: F811
    window = build_window(tmp_path, monkeypatch)
    try:
        for workspace in (*ENABLED[1:], ENABLED[0]):
            click(window.navigation.buttons[workspace])
        assert window.session_owner.state is SessionState.IDLE
        assert spies.constructed == [] and not window.capture.running
    finally:
        window.close()
