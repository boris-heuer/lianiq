"""Meeting sessions: busy refusal both ways, Your microphone, Start and End (CAP-0177 WI-04).

AC-19 and AC-22, each UI AND Integration: the page drives a real ``MeetingController`` on
synthetic capture streams and spy engines (``FactorySpy`` in ``_meeting_window.py``) and the
one ``ActiveSessionOwner``. Also the WI-03 review advisories: the controller is built only at
Start and the page keeps its stopper; the drain after **End meeting** is in
``test_meeting_workspace_drain.py``.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from lianiq.config import AppConfig
from lianiq.meeting.controller import MeetingController
from lianiq.ui.shell.session_owner import SessionBusy, SessionState
from lianiq.ui.shell.workspaces import WorkspaceId
from tests._spy_window import spies  # noqa: F401
from tests.ui._language_helpers import start
from tests.ui._meeting_window import (
    HEADSET_MIC,
    MEETING,
    USER,
    assign_table,
    build_meeting_window,
    choose,
    end_and_wait,
    meeting_window,  # noqa: F401
    notice_title,
    start_meeting,
)
from tests.ui.test_main_window_session import click, wait_until

CONVERSATION, CALL_BRIDGE = WorkspaceId.CONVERSATION, WorkspaceId.CALL_BRIDGE

# AC-19 --------------------------------------------------------------------------------------


def test_ac19_start_meeting_is_refused_while_the_conversation_runs(window) -> None:
    assign_table(window)
    window.show_workspace(CONVERSATION)
    start(window)
    window.show_workspace(MEETING)
    meeting = window.meeting
    assert meeting.start_button.toolTip() == "Stop the Conversation session first"

    click(meeting.start_button)

    assert notice_title(window, MEETING) == "Stop the Conversation session first"
    assert window.meeting_factory.calls == [] and meeting.controller is None
    assert window.meeting_factory.streams.created == []  # nothing was opened
    assert window.session_owner.active is CONVERSATION and window.capture.running
    window.stop_active_session()
    assert wait_until(lambda: notice_title(window, MEETING) == "")  # retry is possible


def test_ac19_start_meeting_is_refused_while_the_call_bridge_holds_the_session(window) -> None:
    assign_table(window)
    owner = window.session_owner
    generation = owner.request_start(CALL_BRIDGE)
    owner.mark_running(generation)

    click(window.meeting.start_button)

    assert notice_title(window, MEETING) == "Stop the Call Bridge session first"
    assert window.meeting_factory.calls == [] and owner.active is CALL_BRIDGE
    owner.mark_idle(generation)


def test_ac19_ui_conversation_and_call_bridge_are_refused_while_the_meeting_runs(window) -> None:
    assign_table(window)
    start_meeting(window)
    assert window.session_owner.active is MEETING
    assert window.session_owner.state is SessionState.RUNNING
    busy = "Stop the Meeting session first"
    assert window.session_strip.state_label.text() == "Meeting running"

    window.start_listening()  # F8
    assert notice_title(window, CONVERSATION) == busy and not window.capture.running
    assert window.start_button.toolTip() == busy and not window.start_button.isEnabled()
    bridge_start = window.call_bridge_panel.start_button
    assert not bridge_start.isEnabled() and bridge_start.toolTip() == busy
    window.start_call_bridge()  # its own gate refuses first; the owner would refuse too
    assert window.call_bridge_controller is None and window.session_owner.active is MEETING

    end_and_wait(window)
    assert window.session_owner.state is SessionState.IDLE
    assert window.start_button.isEnabled()  # Conversation may start again


def test_ac19_integration_the_controller_takes_the_reserved_session(window) -> None:
    owner = window.session_owner
    assign_table(window)
    start_meeting(window)
    controller = window.meeting.controller
    assert isinstance(controller, MeetingController) and controller.running
    assert owner.active is MEETING and owner.generation == 1
    for mode in (CONVERSATION, CALL_BRIDGE, MEETING):
        with pytest.raises(SessionBusy) as refused:
            owner.request_start(mode)
        assert str(refused.value) == "Stop the Meeting session first"
    streams = window.meeting_factory.streams.created
    assert [stream.started for stream in streams] == [True, True]  # both inputs listen


# AC-22 --------------------------------------------------------------------------------------


def test_ac22_an_explicit_your_microphone_is_used_and_kept_after_a_restart(
    tmp_path,
    spies,  # noqa: F811
    monkeypatch,
) -> None:
    window = build_meeting_window(tmp_path / "first", monkeypatch)
    try:
        assign_table(window)
        choose(window, USER, HEADSET_MIC)
        meeting = window.config.meeting
        assert (meeting.user_input_policy, meeting.user_input_endpoint_id) == (
            "explicit",
            HEADSET_MIC.endpoint_id,
        )
        start_meeting(window)
        _session, endpoints, _options = window.meeting_factory.calls[-1]
        assert endpoints.user_capture == HEADSET_MIC
        streams = window.meeting_factory.streams
        assert streams.device(HEADSET_MIC.runtime_index).started  # that endpoint is opened
        end_and_wait(window)
        saved = tmp_path / "settings.local.json"
        window.config.save(saved)  # the settings save of the close (persist_settings)
    finally:
        window.close()
    reloaded = AppConfig.load(saved).meeting

    def restore(config, _root) -> None:
        config.meeting = reloaded

    window = build_meeting_window(tmp_path / "second", monkeypatch, configure=restore)
    try:
        assert window.meeting.combos[USER].currentData() == HEADSET_MIC.endpoint_id
        start_meeting(window)
        _session, endpoints, _options = window.meeting_factory.calls[-1]
        assert endpoints.user_capture == HEADSET_MIC
    finally:
        end_and_wait(window)
        window.close()


# Start and End (WI-03 review advisories) ----------------------------------------------------


def test_the_controller_is_built_only_at_start_and_the_page_keeps_its_stopper(window) -> None:
    owner = window.session_owner
    assert window.meeting.controller is None and window.meeting_factory.calls == []
    assign_table(window)
    start_meeting(window)
    assert len(window.meeting_factory.calls) == 1
    stopper = owner._stoppers[MEETING]
    assert stopper.__self__ is window.meeting and stopper.__name__ == "stop_meeting"
    assert window.pipeline.recognizer is not None  # the models were prepared before


def test_the_app_factory_builds_the_controller_on_the_shared_engines(window) -> None:
    from lianiq.app import build_meeting_controller
    from lianiq.ui.shell.session_owner import ActiveSessionOwner

    assign_table(window)
    window.pipeline.prepare(window.meeting.session())
    owner = ActiveSessionOwner()
    controller = build_meeting_controller(
        window.config,
        window.pipeline,
        window.meeting.session(),
        window.meeting.meeting_endpoints(),
        window.meeting._options(),
        owner,
        lambda _event: None,
    )
    assert controller.engines.recognizer is window.pipeline.recognizer
    assert controller.engines.translator is window.pipeline.translator
    assert controller.engines.synthesizer is window.pipeline.synthesizer
    assert not controller.running and owner.state is SessionState.IDLE


def test_end_meeting_while_the_models_load_cancels_and_opens_nothing(window, spies) -> None:  # noqa: F811
    spies.release_warm_up.clear()  # the translator warm-up waits until released
    assign_table(window)
    click(window.meeting.start_button)
    assert window.meeting.starting and window.session_owner.state is SessionState.STARTING
    assert window.meeting.end_button.isEnabled()
    click(window.meeting.end_button)
    assert not window.meeting.active() and window.session_owner.state is SessionState.IDLE
    spies.release_warm_up.set()
    assert wait_until(lambda: window.pipeline.translator.warm_up_calls == 1)
    settle()
    assert window.meeting_factory.calls == [] and window.meeting.controller is None


def settle() -> None:
    """Let a late ``models_ready`` signal arrive."""
    from PySide6.QtTest import QTest

    QTest.qWait(50)
