"""F8 per page, F9 idle no-op, repeated and failing stops, lingering guard.

session-status-truthfulness WI-01, offscreen UI-nav halves of AC-01..AC-05 (spec §2.2.1,
§2.2.2). The Unit halves are in ``test_shell_session_owner.py``.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from lianiq.ui import notice_catalog as catalog
from lianiq.ui import strings_session as S
from lianiq.ui.shell.session_owner import SessionState
from lianiq.ui.shell.workspaces import WorkspaceId
from tests._spy_window import spies  # noqa: F401
from tests.ui._call_bridge_window import build_call_bridge_window, wait_until
from tests.ui._language_helpers import start

CONVERSATION, LISTEN = WorkspaceId.CONVERSATION, WorkspaceId.LISTEN
MEETING, CALL_BRIDGE = WorkspaceId.MEETING, WorkspaceId.CALL_BRIDGE
NO_SESSION_PAGES = (
    WorkspaceId.TEXT_TRANSLATION,
    WorkspaceId.LANGUAGE_PACKS,
    WorkspaceId.SETTINGS,
)
# The page's Start callable as its button runs it: (workspace attribute, method).
STARTERS = {
    CONVERSATION: ("conversation", "start_listening"),
    LISTEN: ("listen", "start"),
    MEETING: ("meeting", "start_meeting"),
    CALL_BRIDGE: ("call_bridge", "start_call_bridge"),
}


@pytest.fixture
def window(tmp_path, spies, monkeypatch):  # noqa: F811
    window = build_call_bridge_window(tmp_path, monkeypatch)
    yield window
    window.stop_call_bridge()
    window.stop_listening()
    window.close()


def key(window, name: str) -> None:
    """Press F8/F9 as the user does: the shortcut of the active window."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    window.activateWindow()
    assert wait_until(lambda: QApplication.activeWindow() is window)
    target = window.navigation.buttons[window.current_workspace()]
    QTest.keyClick(target, getattr(Qt.Key, f"Key_{name}"))


def spy_starters(window, monkeypatch) -> list[WorkspaceId]:
    calls: list[WorkspaceId] = []
    for workspace, (attribute, method) in STARTERS.items():
        monkeypatch.setattr(
            getattr(window, attribute), method, lambda workspace=workspace: calls.append(workspace)
        )
    return calls


@pytest.mark.parametrize("page", list(STARTERS))
def test_ac01_f8_runs_the_shown_pages_start_callable(window, monkeypatch, page) -> None:
    calls = spy_starters(window, monkeypatch)
    assert window.show_workspace(page)

    key(window, "F8")

    assert calls == [page]  # that page's mode only, never Conversation instead
    assert window.session_owner.state is SessionState.IDLE  # the spies start nothing


def test_ac01_f8_on_the_meeting_page_is_refused_like_its_button(window) -> None:
    start(window)  # Conversation holds the session
    generation = window.session_owner.generation
    window.show_workspace(MEETING)

    key(window, "F8")

    assert window.notices.get(catalog.busy_key(MEETING)) is not None
    assert window.meeting.controller is None and not window.meeting.active()
    owner = window.session_owner
    assert (owner.active, owner.generation) == (CONVERSATION, generation)
    assert window.capture.running  # the running session continues


@pytest.mark.parametrize("page", NO_SESSION_PAGES)
def test_ac02_f8_on_a_page_without_a_session_shows_the_hint(window, monkeypatch, page) -> None:
    calls = spy_starters(window, monkeypatch)
    window.show_workspace(page)

    key(window, "F8")

    assert calls == []
    assert window.session_owner.state is SessionState.IDLE
    assert window.statusBar().currentMessage() == S.F8_NO_SESSION_PAGE


@pytest.mark.parametrize("label", ["Model error", S.STATE_ERROR])
def test_ac03_f9_while_idle_changes_nothing(window, monkeypatch, label) -> None:
    stops: list[str] = []
    monkeypatch.setattr(window.conversation, "stop_listening", lambda: stops.append("stop"))
    window.show_error("The model could not be loaded")
    window.state_label.setText(label)
    window.statusBar().showMessage("Before F9")
    live = window.notices.live()

    key(window, "F9")
    window.stop_active_session()  # the strip's Stop: the same no-op

    assert stops == []
    assert window.state_label.text() == label
    assert window.notices.live() == live
    assert window.statusBar().currentMessage() == "Before F9"


def test_ac04_a_second_stop_while_stopping_calls_the_stopper_once(window) -> None:
    start(window)
    owner, calls = window.session_owner, []
    owner.register(CONVERSATION, lambda: calls.append("stop"), asynchronous=True)

    key(window, "F9")
    key(window, "F9")
    window.stop_active_session()

    assert calls == ["stop"] and owner.state is SessionState.STOPPING
    assert not window.stop_button.isEnabled()
    assert window.session_strip.state_label.text() == "Conversation stopping…"
    owner.mark_idle(owner.generation)


def test_ac04_a_raising_stopper_ends_the_session_with_a_notice(window) -> None:
    start(window)
    owner = window.session_owner
    real_stop = window.conversation.stop_listening

    def broken() -> None:
        raise RuntimeError("worker refused to stop")

    owner.register(CONVERSATION, broken)

    key(window, "F9")

    assert owner.state is SessionState.IDLE and owner.active is None
    notice = window.notices.get(catalog.STOP_FAILED_KEY)
    assert notice is not None and notice.workspace is CONVERSATION
    assert notice.title == S.SESSION_STOP_FAILED.format(mode="Conversation")
    assert not window.session_strip.isVisible()
    owner.register(CONVERSATION, real_stop)
    real_stop()  # the test closes the fake capture; a new Start is possible again
    start(window)
    assert owner.state is SessionState.RUNNING


def test_ac05_a_lingering_worker_refuses_every_start_until_it_exits(window) -> None:
    owner, alive = window.session_owner, [True]
    owner.linger(CONVERSATION, lambda: alive[0])

    window.start_button.click()  # Conversation's own Start
    window.show_workspace(MEETING)
    key(window, "F8")  # Meeting's Start

    assert not window.capture.running and window.meeting.controller is None
    assert owner.state is SessionState.IDLE
    notice = window.notices.get(catalog.STILL_FINISHING_KEY)
    assert notice is not None
    assert notice.title == S.SESSION_STILL_FINISHING.format(mode="Conversation")

    alive[0] = False  # the worker exited: the next Start works without other action
    window.show_workspace(CONVERSATION)
    start(window)
    assert owner.state is SessionState.RUNNING and owner.lingering() is None
    assert window.notices.get(catalog.STILL_FINISHING_KEY) is None  # resolved on running
