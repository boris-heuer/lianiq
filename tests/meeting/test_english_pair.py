"""English ↔ Mandarin (Simplified) Meeting and the socket guard (CAP-0181 AC-10, AC-15).

Integration tests on the synthetic adapters and spy engines of ``tests/meeting/support.py``
with English as the local language; the Conversation half of AC-15 reuses the AC-08 run of
``tests/test_conversation_routing.py``.
"""

from __future__ import annotations

import socket

import pytest

from lianiq.languages import BUILTIN_REGISTRY, MEETING_MODE, LanguageId, SessionPair
from lianiq.meeting import MeetingRole
from lianiq.meeting.controller import MeetingEventKind as Kind
from tests.meeting.support import TABLE_SPEAKER, ZH, Line, Played, say, wait_until
from tests.test_conversation_routing import (
    test_cap0181_ac08_english_mandarin_routes_both_members_and_holds_german as conversation,
)

EN = LanguageId("en")
TABLE, USER = MeetingRole.TABLE_CAPTURE, MeetingRole.USER_CAPTURE
SESSION = SessionPair(BUILTIN_REGISTRY.pair(EN, ZH), MEETING_MODE, local_language=EN)
# 10 Mandarin at the table, 20 English at the PO microphone, 30 English at the table (0.7).
SCRIPT = {10: Line(ZH, "你好，欢迎"), 20: Line(EN, "Good morning"), 30: Line(EN, "Hello", 0.7)}


@pytest.fixture
def network_attempts(monkeypatch) -> list[tuple]:
    attempts: list[tuple] = []

    def refuse(*args, **kwargs):
        attempts.append(args)
        raise AssertionError("network access")

    for owner, name in (
        (socket.socket, "connect"),
        (socket.socket, "connect_ex"),
        (socket, "create_connection"),
        (socket, "getaddrinfo"),
    ):
        monkeypatch.setattr(owner, name, refuse)
    return attempts


def run_english_meeting(meeting):
    harness = meeting(SCRIPT, session=SESSION)
    controller = harness.controller
    controller.start()
    say(controller, TABLE, 10)
    assert wait_until(lambda: len(controller.results) == 1)
    say(controller, TABLE, 30)  # before any playback mutes the table input
    assert wait_until(lambda: harness.events.of(Kind.IGNORED))
    say(controller, USER, 20)
    assert wait_until(lambda: len(controller.results) == 2)
    return harness


def test_ac10_english_lines_mandarin_on_the_table_speaker_and_english_at_the_table_dropped(
    meeting,
) -> None:
    harness = run_english_meeting(meeting)

    lines = [event.line for event in harness.events.of(Kind.LINE)]
    assert [(line.role, line.text) for line in lines] == [
        (TABLE, "[zh-Hans>en] 你好，欢迎"),  # an English "Table" line
        (USER, "Good morning"),  # the English "You" line
    ]
    assert harness.renders.played == [Played(TABLE_SPEAKER, ZH)]  # nowhere else
    assert harness.synthesizer.calls == [("[en>zh-Hans] Good morning", ZH)]
    ignored = [(event.role, event.count) for event in harness.events.of(Kind.IGNORED)]
    assert ignored == [(TABLE, 1)]
    assert len(harness.controller.results) == 2
    assert "Hello" not in repr(harness.events.items) + repr(harness.controller.results)


def test_ac15_english_meeting_and_conversation_attempt_no_network(
    meeting, network_attempts
) -> None:
    harness = run_english_meeting(meeting)
    assert harness.controller.stop(timeout=10.0)
    conversation()

    assert network_attempts == []
    assert harness.events.items[-1].kind is Kind.STOPPED
