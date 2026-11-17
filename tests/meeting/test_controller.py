"""Meeting controller: inputs, worker, queue order, gate and session owner (CAP-0177 WI-03).

Integration tests on synthetic capture/render adapters, spy engines and a fake clock
(``tests/meeting/support.py``). Each test names the spec §5 acceptance criterion it proves.
"""

from __future__ import annotations

import subprocess
import sys
import threading
from pathlib import Path

import pytest

from lianiq.audio.segmenter import UtteranceSegmenter
from lianiq.meeting import MeetingRole
from lianiq.meeting.capture import MeetingCapture
from lianiq.meeting.controller import MeetingEventKind as Kind
from lianiq.ui.shell.session_owner import ActiveSessionOwner, SessionBusy, SessionState
from lianiq.ui.shell.workspaces import WorkspaceId
from tests.meeting.conftest import meeting_endpoints
from tests.meeting.support import (
    AUDIO,
    DE,
    LOCAL_OUTPUT,
    TABLE_MIC,
    TABLE_SPEAKER,
    USER_MIC,
    ZH,
    Line,
    Played,
    pause,
    say,
    speech,
    wait_until,
)

TABLE, USER = MeetingRole.TABLE_CAPTURE, MeetingRole.USER_CAPTURE
SCRIPT = {10: Line(ZH, "你好，欢迎"), 20: Line(DE, "Guten Tag")}


def test_ac07_unit_each_input_segmenter_ends_its_own_contribution_after_a_pause() -> None:
    """AC-07 (Unit, segmenter): each input has its own segmenter; a pause ends a turn."""
    ended: dict[str, list[int]] = {"table": [], "user": []}
    endpoints = meeting_endpoints()
    sources = {"table": endpoints.table_capture, "user": endpoints.user_capture}
    captures = {
        name: MeetingCapture(
            sources[name],
            AUDIO,
            lambda utterance, name=name: ended[name].append(utterance.samples.size),
            is_muted=lambda: False,
            on_unmuted=lambda: None,
        )
        for name in ended
    }
    assert all(isinstance(c._segmenter, UtteranceSegmenter) for c in captures.values())
    assert captures["table"]._segmenter is not captures["user"]._segmenter
    table_blocks = [*speech(1, 6), *pause()]
    user_blocks = [*pause(4), *speech(2, 4), *pause()]  # it ends two blocks later
    for index in range(max(len(table_blocks), len(user_blocks))):
        for name, blocks in (("table", table_blocks), ("user", user_blocks)):
            if index < len(blocks):
                captures[name].process_block(blocks[index])
        if index == len(table_blocks) - 1:
            assert len(ended["table"]) == 1 and ended["user"] == []
    assert [len(ended["table"]), len(ended["user"])] == [1, 1]


def test_ac07_integration_both_inputs_form_contributions_without_a_button(meeting) -> None:
    """AC-07 (Integration): audio callbacks of both inputs → two contributions, no button."""
    harness = meeting(SCRIPT)
    harness.controller.start()
    for index, tag in ((TABLE_MIC, 10), (USER_MIC, 20)):
        callback = harness.streams.device(index).callback
        for block in [*speech(tag), *pause()]:
            callback(block.reshape(-1, 1), block.size, object(), None)
    assert wait_until(lambda: len(harness.controller.results) == 2)
    assert {r.source_language for r in harness.controller.results} == {DE, ZH}


def test_ac04_ac06_table_line_translation_and_po_speech_on_the_table_speaker_only(
    meeting,
) -> None:
    """VoR-01 / AC-04 / AC-06: a Table line in the local language; PO speech → table speaker."""
    harness = meeting(SCRIPT, speak_local=False)
    controller = harness.controller
    controller.start()
    say(controller, TABLE, 10)
    assert wait_until(lambda: len(controller.results) == 1)
    say(controller, USER, 20)
    assert wait_until(lambda: len(controller.results) == 2)

    lines = [event.line for event in harness.events.of(Kind.LINE)]
    assert [(line.role, line.text) for line in lines] == [
        (TABLE, "[zh-Hans>de] 你好，欢迎"),
        (USER, "Guten Tag"),  # the PO's recognised local-language text
    ]
    assert harness.events.of(Kind.PENDING)[0].contribution_id == lines[0].contribution_id
    assert harness.renders.played == [Played(TABLE_SPEAKER, ZH)]  # nowhere else
    assert harness.synthesizer.calls == [("[de>zh-Hans] Guten Tag", ZH)]


@pytest.mark.parametrize("speak_local", [True, False])
def test_ac05_local_speech_plays_on_its_output_only_when_switched_on(meeting, speak_local) -> None:
    """AC-05 (Integration): local-language speech on the chosen output iff the switch is on."""
    harness = meeting(SCRIPT, speak_local=False)
    harness.controller.set_speak_local(speak_local)
    harness.controller.start()
    say(harness.controller, TABLE, 10)
    assert wait_until(lambda: len(harness.controller.results) == 1)
    expected = [Played(LOCAL_OUTPUT, DE)] if speak_local else []
    assert harness.renders.played == expected
    assert len(harness.events.of(Kind.LINE)) == 1  # the text is still shown


def test_local_speech_needs_its_own_output(meeting) -> None:
    harness = meeting(SCRIPT, endpoints=meeting_endpoints(local=False))
    with pytest.raises(ValueError):
        harness.controller.set_speak_local(True)


def test_ac13_twenty_overlapping_pairs_are_all_translated_in_speech_end_order(meeting) -> None:
    """AC-13: contributions ending on both inputs within 1 s; 20 pairs, none dropped."""
    script = {1: Line(ZH, "开始")}
    for pair in range(20):
        script[100 + pair] = Line(ZH, f"桌子 {pair}")
        script[300 + pair] = Line(DE, f"Satz {pair}")
    harness = meeting(script, step_ms=400.0)  # the two ends of a pair are 400 ms apart
    controller = harness.controller
    harness.recognizer.hold = hold = threading.Event()
    controller.start()
    say(controller, TABLE, 1)  # the worker is busy with this one while the pairs arrive
    assert wait_until(lambda: harness.recognizer.hold is None)
    for pair in range(20):
        long_, short = (TABLE, USER) if pair % 2 else (USER, TABLE)
        tags = {TABLE: 100 + pair, USER: 300 + pair}
        blocks = {
            long_: [*speech(tags[long_], 5), *pause()],
            short: [*speech(tags[short], 3), *pause()],
        }
        for index in range(8):  # both inputs speak at the same time
            for role in (TABLE, USER):
                if index < len(blocks[role]):
                    controller.captures[role].process_block(blocks[role][index])
    assert harness.events.of(Kind.FALLING_BEHIND)  # AC-14: noticed, nothing dropped
    hold.set()
    assert wait_until(lambda: len(controller.results) == 41, timeout=10.0)

    processed = [tag for tag, language in harness.recognizer.calls if language is None]
    assert sorted(processed) == sorted(script)  # every contribution, exactly once
    lines = [event.line for event in harness.events.of(Kind.LINE)]
    assert len(lines) == 41
    assert [line.ended_at for line in lines] == sorted(line.ended_at for line in lines)
    for pair in range(1, 20):  # the pair whose table input spoke longer ends table last
        order = [tag for tag in processed if tag in (100 + pair, 300 + pair)]
        assert order == ([300 + pair, 100 + pair] if pair % 2 else [100 + pair, 300 + pair])
    assert harness.events.of(Kind.CAUGHT_UP)


def test_ac08_ac09_other_language_contributions_are_discarded_and_counted(meeting) -> None:
    """AC-08/AC-09 (Integration): other pair language at ≥ threshold → ignored, no text."""
    script = {11: Line(DE, "falsche Sprache"), 21: Line(ZH, "错误的语言"), 22: Line(ZH, "嗯", 0.4)}
    harness = meeting({**script, 23: Line(None, "x", 0.9, "Hallo")})
    controller = harness.controller
    controller.start()
    for role, tag in ((TABLE, 11), (USER, 21), (USER, 21), (USER, 22), (USER, 23)):
        say(controller, role, tag)
    assert wait_until(lambda: len(harness.recognizer.calls) == 7)
    assert wait_until(lambda: len(controller.results) == 2)

    ignored = [(event.role, event.count) for event in harness.events.of(Kind.IGNORED)]
    assert ignored == [(TABLE, 1), (USER, 1), (USER, 2)]
    assert len(harness.events.of(Kind.WITHDRAWN)) == 1  # the table placeholder
    published = repr(harness.events.items) + repr(controller.results)
    assert "falsche Sprache" not in published and "错误的语言" not in published
    # AC-10 forced pass: low probability or a language outside the pair → expected language.
    assert harness.recognizer.calls[-4:] == [(22, None), (22, DE), (23, None), (23, DE)]
    assert [result.source_text for result in controller.results] == ["嗯", "Hallo"]


def test_meeting_takes_the_session_as_meeting_and_releases_it_on_stop(meeting) -> None:
    owner = ActiveSessionOwner()
    states: list[tuple[SessionState, WorkspaceId | None]] = []
    owner.subscribe(lambda state, active: states.append((state, active)))
    harness = meeting(SCRIPT, owner=owner)
    harness.controller.start()
    assert (owner.state, owner.active) == (SessionState.RUNNING, WorkspaceId.MEETING)
    assert {stream.kwargs["device"] for stream in harness.streams.created} == {TABLE_MIC, USER_MIC}
    owner.stop()  # F9 from any workspace uses the registered stopper
    assert owner.state is SessionState.IDLE
    assert harness.events.of(Kind.STOPPED)
    assert not any(stream.started for stream in harness.streams.created)


def test_a_busy_session_refuses_the_meeting_before_any_stream_opens(meeting) -> None:
    owner = ActiveSessionOwner()
    owner.request_start(WorkspaceId.CONVERSATION)
    harness = meeting(SCRIPT, owner=owner)
    with pytest.raises(SessionBusy):
        harness.controller.start()
    assert harness.streams.created == [] and owner.active is WorkspaceId.CONVERSATION


def test_stop_drains_queued_contributions_before_stopped(meeting) -> None:
    """Spec §2.2.1 step 7: End meeting finishes the queued contributions."""
    harness = meeting(SCRIPT)
    controller = harness.controller
    harness.recognizer.hold = hold = threading.Event()
    controller.start()
    for role, tag in ((TABLE, 10), (USER, 20), (TABLE, 10)):
        say(controller, role, tag)
    threading.Timer(0.2, hold.set).start()
    assert controller.stop(timeout=10.0) is True
    assert len(controller.results) == 3
    assert harness.events.items[-1].kind is Kind.STOPPED


def test_stop_never_blocks_forever_on_a_hung_contribution(meeting) -> None:
    """WI-01 review advisory: ``stop`` drains with a finite timeout."""
    harness = meeting(SCRIPT)
    harness.recognizer.hold = hold = threading.Event()
    harness.controller.start()
    say(harness.controller, TABLE, 10)
    say(harness.controller, USER, 20)
    assert harness.controller.stop(timeout=0.2) is False
    assert harness.events.items[-1].kind is Kind.STOPPED
    assert harness.owner.state is SessionState.IDLE
    hold.set()


def test_a_user_microphone_that_is_the_table_microphone_is_refused(meeting) -> None:
    endpoints = meeting_endpoints()
    same = type(endpoints)(endpoints.table_capture, endpoints.table_render, endpoints.table_capture)
    with pytest.raises(ValueError):
        meeting(SCRIPT, endpoints=same)


def test_silence_from_the_forced_pass_is_dropped_not_counted(meeting) -> None:
    """Contract §2: an empty forced pass is silence, not "other language"."""
    harness = meeting({12: Line(None, "", 0.2, "")})
    harness.controller.start()
    say(harness.controller, TABLE, 12)
    assert wait_until(lambda: harness.events.of(Kind.WITHDRAWN))
    assert harness.events.of(Kind.IGNORED) == [] and harness.controller.results == ()


def test_the_controller_and_transcript_modules_are_qt_free() -> None:
    modules = "lianiq.meeting.controller, lianiq.meeting.transcript"
    script = f"import sys, {modules}; print(any(m.startswith('PySide6') for m in sys.modules))"
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        check=True,
        cwd=Path(__file__).resolve().parents[2],
        text=True,
    )
    assert result.stdout.strip() == "False"
