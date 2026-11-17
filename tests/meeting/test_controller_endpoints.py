"""Meeting endpoint loss on synthetic adapters (CAP-0177 WI-03, contract §5; AC-15).

Modelled on ``call_bridge/controller.py``: the lost capture stops or the lost render is
skipped, ``ENDPOINT_LOST`` names the role, no other device is opened, queued contributions
still finish.
"""

from __future__ import annotations

import threading

from lianiq.audio.endpoints import EndpointInventory
from lianiq.meeting import MeetingRole
from lianiq.meeting.controller import MeetingEventKind as Kind
from tests.meeting.conftest import meeting_endpoints
from tests.meeting.support import DE, TABLE_MIC, ZH, Line, say, wait_until

TABLE, USER = MeetingRole.TABLE_CAPTURE, MeetingRole.USER_CAPTURE
SCRIPT = {10: Line(ZH, "你好"), 20: Line(DE, "Hallo"), 21: Line(DE, "Noch einmal")}


def test_ac15_a_lost_capture_stops_and_queued_contributions_still_finish(meeting) -> None:
    harness = meeting(SCRIPT)
    controller = harness.controller
    harness.recognizer.hold = hold = threading.Event()
    controller.start()
    opened = len(harness.streams.created)
    say(controller, TABLE, 10)
    say(controller, USER, 20)
    controller.endpoint_lost(TABLE)
    controller.endpoint_lost(TABLE)  # reported once
    hold.set()
    assert wait_until(lambda: len(controller.results) == 2)

    assert [event.role for event in harness.events.of(Kind.ENDPOINT_LOST)] == [TABLE]
    assert not harness.streams.device(TABLE_MIC).started
    assert len(harness.streams.created) == opened  # no other device was opened
    assert controller.lost_roles == {TABLE}


def test_ac15_a_lost_table_render_skips_speech_but_keeps_the_text(meeting) -> None:
    harness = meeting(SCRIPT)
    controller = harness.controller
    controller.start()
    controller.endpoint_lost(MeetingRole.TABLE_RENDER)
    say(controller, USER, 20)
    assert wait_until(lambda: len(controller.results) == 1)
    assert harness.renders.played == [] and harness.synthesizer.calls == []
    assert controller.results[0].source_text == "Hallo"


def test_reconcile_reports_every_assigned_endpoint_missing_from_the_inventory(meeting) -> None:
    endpoints = meeting_endpoints()
    harness = meeting(SCRIPT, endpoints=endpoints)
    harness.controller.start()
    present = (endpoints.table_capture, endpoints.table_render, endpoints.local_render)
    harness.controller.reconcile_endpoints(EndpointInventory(present))
    assert [event.role for event in harness.events.of(Kind.ENDPOINT_LOST)] == [USER]
    say(harness.controller, TABLE, 10)
    assert wait_until(lambda: len(harness.controller.results) == 1)  # the meeting continues


def test_an_engine_failure_withdraws_the_contribution_and_the_worker_continues(
    meeting, caplog
) -> None:
    harness = meeting(SCRIPT)  # tag 99 is not in the script: the recogniser raises
    controller = harness.controller
    controller.start()
    say(controller, TABLE, 99)
    say(controller, TABLE, 10)
    assert wait_until(lambda: len(controller.results) == 1)
    assert len(harness.events.of(Kind.WITHDRAWN)) == 1
    assert "category=stt_failure" in caplog.text


def test_a_capture_that_fails_to_stop_still_stops_the_other_and_drains(meeting) -> None:
    """``stop`` stops both captures and drains even if one capture's stop raises (WI-05)."""
    from lianiq.ui.shell.session_owner import SessionState

    harness = meeting(SCRIPT)
    controller = harness.controller
    controller.start()
    harness.recognizer.hold = hold = threading.Event()
    say(controller, USER, 20)
    say(controller, USER, 21)
    table = controller.captures[TABLE]

    def broken_stop() -> None:
        raise RuntimeError("PortAudio refused")

    table.stop = broken_stop
    threading.Timer(0.2, hold.set).start()
    assert controller.stop(timeout=5.0)
    assert not controller.captures[USER].running
    assert len(controller.results) == 2  # drained before STOPPED
    assert [event.kind for event in harness.events.items][-1] is Kind.STOPPED
    assert harness.owner.state is SessionState.IDLE
