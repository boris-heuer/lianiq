"""Meeting transcript text and its atomic UTF-8 write (CAP-0177 WI-03, contract §5; AC-16)."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from lianiq.domain import TranslationResult
from lianiq.languages.session import format_transcript_v2
from lianiq.meeting import MeetingRole
from lianiq.meeting.transcript import meeting_transcript_text, write_meeting_transcript
from tests.meeting.support import DE, DE_ZH, ZH, Line, say, wait_until

START = datetime(2026, 11, 17, 10, 0, tzinfo=timezone(timedelta(hours=1)))


def result(seconds: int, source, target, source_text: str, translated: str) -> TranslationResult:
    return TranslationResult(
        uuid4(), START + timedelta(seconds=seconds), source_text, translated, source, target, 1, 1
    )


def test_ac16_the_text_is_transcript_v2_with_both_directions_in_speech_end_order() -> None:
    results = [
        result(5, DE, ZH, "Guten Tag", "你好"),
        result(2, ZH, DE, "欢迎", "Willkommen"),
    ]
    text = meeting_transcript_text(DE_ZH, results)

    assert text == format_transcript_v2(DE_ZH, results)
    assert text.index("欢迎") < text.index("Guten Tag")  # ordered by captured_at
    assert f"{ZH} -> {DE}" in text and f"{DE} -> {ZH}" in text


def test_ac16_write_is_utf8_with_lf_and_replaces_an_existing_file(tmp_path) -> None:
    path = tmp_path / "lianiq-meeting-2026-11-17.txt"
    path.write_text("old", encoding="utf-8")
    text = meeting_transcript_text(DE_ZH, [result(1, ZH, DE, "欢迎", "Willkommen")])

    write_meeting_transcript(path, text)

    assert path.read_bytes() == text.encode("utf-8")
    assert b"\r\n" not in path.read_bytes()
    assert os.listdir(tmp_path) == [path.name]  # no temporary file is left


def test_ac16_a_write_error_raises_oserror_and_leaves_nothing(tmp_path, monkeypatch) -> None:
    with pytest.raises(OSError):
        write_meeting_transcript(tmp_path / "missing" / "t.txt", "text")

    def fail(*_args):
        raise PermissionError("denied")

    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(OSError, match="denied"):
        write_meeting_transcript(tmp_path / "t.txt", "text")
    assert os.listdir(tmp_path) == []


def test_ac16_the_controller_results_become_the_transcript(meeting) -> None:
    """Integration: only translated contributions, both languages per turn."""
    script = {10: Line(ZH, "欢迎"), 20: Line(DE, "Danke"), 11: Line(DE, "andere Sprache")}
    harness = meeting(script)
    controller = harness.controller
    controller.start()
    for role, tag in ((MeetingRole.TABLE_CAPTURE, 10), (MeetingRole.USER_CAPTURE, 20)):
        say(controller, role, tag)
    say(controller, MeetingRole.TABLE_CAPTURE, 11)  # discarded: never in the transcript
    assert wait_until(lambda: len(harness.recognizer.calls) == 3)
    controller.stop(timeout=5.0)

    text = meeting_transcript_text(DE_ZH, controller.results)
    assert "andere Sprache" not in text
    lines = text.splitlines()
    assert lines[2].endswith(f"{ZH} -> {DE}")
    assert lines[3:5] == [f"{ZH}: 欢迎", f"{DE}: [zh-Hans>de] 欢迎"]
    assert f"{DE}: Danke" in text and f"{ZH}: [de>zh-Hans] Danke" in text
