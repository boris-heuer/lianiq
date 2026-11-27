"""Meeting controller stop report and event generation (session-status-truthfulness WI-04).

``MeetingController.stop`` returns a ``MeetingStopResult``: the contributions withdrawn at the
(shortened) drain bound plus the one still in flight; withdrawn table placeholders are
published as ``NOT_FINISHED``; every event carries the meeting's owner generation (AC-17,
AC-18). No real long waits: the bounds are parameters.
"""

from __future__ import annotations

import threading

from lianiq.meeting import MeetingRole
from lianiq.meeting.controller import MeetingEventKind as Kind
from lianiq.meeting.events import MeetingStopResult
from lianiq.ui.shell.session_owner import ActiveSessionOwner, SessionState
from lianiq.ui.shell.workspaces import WorkspaceId
from tests.meeting.support import DE, ZH, Line, say, wait_until

TABLE, USER = MeetingRole.TABLE_CAPTURE, MeetingRole.USER_CAPTURE
SCRIPT = {10: Line(ZH, "你好，欢迎"), 11: Line(ZH, "谢谢"), 20: Line(DE, "Guten Tag")}


def test_ac17_a_hung_drain_reports_and_withdraws_its_unfinished_contributions(meeting) -> None:
    harness = meeting(SCRIPT)
    harness.recognizer.hold = hold = threading.Event()
    controller = harness.controller
    controller.start()
    for role, tag in ((TABLE, 10), (TABLE, 11), (USER, 20)):
        say(controller, role, tag)
    assert wait_until(lambda: controller.unfinished() == 3)  # one in flight, two queued
    result = controller.stop(timeout=0.2, grace=0.1)
    assert result == MeetingStopResult(3, True) and not result
    pending = [e.contribution_id for e in harness.events.of(Kind.PENDING)]
    withdrawn = [e.contribution_id for e in harness.events.of(Kind.NOT_FINISHED)]
    assert sorted(map(str, withdrawn)) == sorted(map(str, pending))  # both table rows stay
    assert harness.events.of(Kind.WITHDRAWN) == []  # none vanishes
    assert harness.events.items[-1].stop == result and controller.worker_alive()
    assert harness.owner.state is SessionState.IDLE
    hold.set()
    assert wait_until(lambda: not controller.worker_alive())


def test_a_clean_drain_reports_nothing_unfinished(meeting) -> None:
    harness = meeting(SCRIPT)
    controller = harness.controller
    controller.start()
    say(controller, TABLE, 10)
    assert wait_until(lambda: len(controller.results) == 1)
    assert controller.stop(timeout=5.0) == MeetingStopResult(0, False)
    assert controller.unfinished() == 0 and not controller.worker_alive()


def test_ac18_every_event_carries_the_owner_generation_of_its_meeting(meeting) -> None:
    owner = ActiveSessionOwner()
    owner.mark_idle(owner.request_start(WorkspaceId.CONVERSATION))  # an earlier session
    harness = meeting(SCRIPT, owner=owner)
    controller = harness.controller
    controller.start()
    say(controller, TABLE, 10)
    assert wait_until(lambda: len(controller.results) == 1)
    controller.stop(timeout=5.0)
    kinds = {event.kind for event in harness.events.items}
    assert {Kind.LISTENING, Kind.PENDING, Kind.LINE, Kind.STOPPED} <= kinds
    assert {event.generation for event in harness.events.items} == {2}
