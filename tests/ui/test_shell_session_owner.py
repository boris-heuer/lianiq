"""The workspace registry and the active-session owner (CAP-0168 WI-02; contract.md §1-§2).

Qt-free unit tests: AC-03 (registry order), AC-04/AC-05 (entry states) and the Unit half of
AC-07 (one session across modes, ``SessionBusy`` in both directions, stale generations).
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from lianiq.ui import strings
from lianiq.ui.shell.session_owner import ActiveSessionOwner, SessionBusy, SessionState
from lianiq.ui.shell.workspaces import (
    DEFAULT_ENTRIES,
    EntryState,
    WorkspaceId,
    entry,
    label,
    session_busy_message,
)

CONVERSATION, CALL_BRIDGE = WorkspaceId.CONVERSATION, WorkspaceId.CALL_BRIDGE


class Recorder:
    def __init__(self, owner: ActiveSessionOwner) -> None:
        self.changes: list[tuple[SessionState, WorkspaceId | None]] = []
        owner.subscribe(lambda state, active: self.changes.append((state, active)))


def owner_with_stoppers():
    owner = ActiveSessionOwner()
    stopped: list[WorkspaceId] = []

    def stopper(mode):
        def stop() -> None:
            stopped.append(mode)
            owner.mark_idle(owner.generation)

        return stop

    owner.register(CONVERSATION, stopper(CONVERSATION))
    owner.register(CALL_BRIDGE, stopper(CALL_BRIDGE))
    return owner, stopped


def test_qt_free_modules_never_import_pyside6() -> None:
    code = (
        "import sys\n"
        "import lianiq.ui.shell.workspaces, lianiq.ui.shell.session_owner, lianiq.ui.strings\n"
        "assert not any(name.split('.')[0] == 'PySide6' for name in sys.modules), "
        "sorted(name for name in sys.modules if name.startswith('PySide6'))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr


def test_ac03_registry_lists_six_entries_in_spec_order_with_settings_last() -> None:
    assert [(item.id, item.label, item.state) for item in DEFAULT_ENTRIES] == [
        (WorkspaceId.CONVERSATION, "Conversation", EntryState.ENABLED),
        (WorkspaceId.TEXT_TRANSLATION, "Text translation", EntryState.PLANNED),
        (WorkspaceId.LISTEN, "Listen & translate", EntryState.PLANNED),
        (WorkspaceId.CALL_BRIDGE, "Call Bridge", EntryState.EXPERIMENTAL),
        (WorkspaceId.LANGUAGE_PACKS, "Language packs", EntryState.PLANNED),
        (WorkspaceId.SETTINGS, "Settings", EntryState.ENABLED),
    ]
    assert [item.id.value for item in DEFAULT_ENTRIES] == [
        "conversation",
        "text-translation",
        "listen-and-translate",
        "call-bridge",
        "language-packs",
        "settings",
    ]


def test_ac04_ac05_only_planned_entries_are_not_selectable() -> None:
    assert [item.id for item in DEFAULT_ENTRIES if not item.selectable] == [
        WorkspaceId.TEXT_TRANSLATION,
        WorkspaceId.LISTEN,
        WorkspaceId.LANGUAGE_PACKS,
    ]
    assert entry(CALL_BRIDGE).state is EntryState.EXPERIMENTAL and entry(CALL_BRIDGE).selectable


def test_contract_strings_have_the_english_defaults() -> None:
    assert strings.NAV_PLANNED_DESCRIPTION == "Planned — not available yet"
    assert strings.NAV_EXPERIMENTAL == "Experimental"
    assert strings.STOP_ACTION == "Stop (F9)"
    assert strings.TRANSCRIPT_EMPTY == "Press Start, then speak …"
    assert strings.SESSION_RUNNING.format(mode=label(CONVERSATION)) == "Conversation running"
    assert strings.SESSION_STARTING.format(mode="Call Bridge") == "Call Bridge starting…"
    assert strings.SESSION_STOPPING.format(mode="Conversation") == "Conversation stopping…"
    assert session_busy_message(CONVERSATION) == "Stop the Conversation session first"
    assert session_busy_message(CALL_BRIDGE) == "Stop the Call Bridge session first"


def test_a_start_runs_through_starting_running_and_idle() -> None:
    owner, _stopped = owner_with_stoppers()
    recorder = Recorder(owner)

    generation = owner.request_start(CONVERSATION)
    assert (owner.state, owner.active, owner.generation) == (
        SessionState.STARTING,
        CONVERSATION,
        generation,
    )
    owner.mark_running(generation)
    owner.mark_idle(generation)

    assert recorder.changes == [
        (SessionState.STARTING, CONVERSATION),
        (SessionState.RUNNING, CONVERSATION),
        (SessionState.IDLE, None),
    ]
    assert owner.active is None


@pytest.mark.parametrize(
    ("running", "requested"), [(CONVERSATION, CALL_BRIDGE), (CALL_BRIDGE, CONVERSATION)]
)
@pytest.mark.parametrize("state", [SessionState.STARTING, SessionState.RUNNING])
def test_ac07_a_second_session_is_refused_in_both_directions(running, requested, state) -> None:
    owner, stopped = owner_with_stoppers()
    generation = owner.request_start(running)
    if state is SessionState.RUNNING:
        owner.mark_running(generation)
    recorder = Recorder(owner)

    with pytest.raises(SessionBusy) as refused:
        owner.request_start(requested)

    assert refused.value.active is running
    assert str(refused.value) == f"Stop the {label(running)} session first"
    assert (owner.state, owner.active, owner.generation) == (state, running, generation)
    assert recorder.changes == [] and stopped == []  # nothing stopped, nothing started
    assert owner.busy_for(requested) is running and owner.busy_for(running) is None


def test_ac07_the_same_mode_cannot_start_twice() -> None:
    owner, _stopped = owner_with_stoppers()
    owner.request_start(CONVERSATION)
    with pytest.raises(SessionBusy):
        owner.request_start(CONVERSATION)


def test_stop_calls_the_active_modes_stopper_from_anywhere() -> None:
    owner, stopped = owner_with_stoppers()
    owner.mark_running(owner.request_start(CALL_BRIDGE))
    recorder = Recorder(owner)

    owner.stop()

    assert stopped == [CALL_BRIDGE]
    assert recorder.changes == [(SessionState.STOPPING, CALL_BRIDGE), (SessionState.IDLE, None)]
    owner.request_start(CONVERSATION)  # the next session may start


def test_stop_while_idle_is_a_no_op() -> None:
    owner, stopped = owner_with_stoppers()
    recorder = Recorder(owner)
    owner.stop()
    assert stopped == [] and recorder.changes == []


def test_a_stopper_that_does_not_report_back_still_ends_the_session() -> None:
    owner = ActiveSessionOwner()
    calls = []
    owner.register(CONVERSATION, lambda: calls.append("stop"))
    owner.request_start(CONVERSATION)
    owner.stop()
    assert calls == ["stop"] and owner.state is SessionState.IDLE and owner.active is None


def test_stale_generations_change_nothing() -> None:
    owner, _stopped = owner_with_stoppers()
    first = owner.request_start(CONVERSATION)
    owner.mark_idle(first)
    second = owner.request_start(CALL_BRIDGE)
    recorder = Recorder(owner)

    owner.mark_running(first)
    owner.mark_idle(first)

    assert second == first + 1
    assert (owner.state, owner.active) == (SessionState.STARTING, CALL_BRIDGE)
    assert recorder.changes == []
    owner.mark_running(second)
    assert owner.state is SessionState.RUNNING
