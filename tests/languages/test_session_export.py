"""Transcript export v2 and the session lock (CAP-0169 AC-13, AC-15; contract.md §3.1.7).

Split from ``test_session.py``; the harness is in ``_session_harness.py``.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from lianiq.domain import TranslationResult
from lianiq.languages import (
    TRANSCRIPT_V2_HEADER,
    DeviceReadiness,
    InputKind,
    OutputKind,
    PairLockedError,
    RoutingKind,
    SessionPair,
    UsageMode,
    format_transcript_v2,
)
from tests.languages._session_harness import (
    AUDIO,
    AUTOMATIC,
    DE,
    DE_ZH,
    MICROPHONE_TEXT,
    QAA_QAB,
    ZH,
    Harness,
    ScriptedRecognizer,
    fixed,
)
from tests.languages.synthetic import QAA, QAB


def result(
    captured_at: datetime, source: str = DE, target: str = ZH, text: str = "Guten Tag"
) -> TranslationResult:
    return TranslationResult(
        uuid4(), captured_at, text, f"[{source}>{target}] {text}", source, target, 0.1, 0.2
    )


T0 = datetime(2026, 11, 2, 10, 15, 3, tzinfo=timezone(timedelta(hours=1)))


def test_ac15_translation_result_is_frozen() -> None:
    completed = result(T0)

    for field, value in (("source_language", ZH), ("target_language", DE), ("source_text", "x")):
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(completed, field, value)


def test_export_v2_format_orders_lines_by_capture_time() -> None:
    later = result(T0 + timedelta(seconds=5), ZH, DE, "你好")
    earlier = result(T0)

    text = format_transcript_v2(DE_ZH, [later, earlier])

    assert text.splitlines() == [
        "# lianiq transcript v2",
        "# pair: de zh-Hans",
        "[2026-11-02T10:15:03+01:00] de -> zh-Hans",
        "de: Guten Tag",
        "zh-Hans: [de>zh-Hans] Guten Tag",
        "",
        "[2026-11-02T10:15:08+01:00] zh-Hans -> de",
        "zh-Hans: 你好",
        "de: [zh-Hans>de] 你好",
    ]
    assert text.startswith(TRANSCRIPT_V2_HEADER + "\n")
    assert text.endswith("\n")


def test_ac15_completed_turns_keep_their_languages_after_routing_output_and_pair_change(
    tmp_path,
) -> None:
    recognizer = ScriptedRecognizer(
        [("de", "Guten Tag"), ("zh-Hans", "你好"), ("zh-Hans", "谢谢"), ("qab", "beta")]
    )
    harness = Harness(tmp_path, recognizer, voices=(DE, ZH))
    sessions = [
        AUTOMATIC,  # Automatic de/zh-Hans, text
        fixed(ZH),  # routing change
        fixed(ZH, OutputKind.SPOKEN),  # output change
        SessionPair(QAA_QAB, MICROPHONE_TEXT),  # pair change
    ]
    snapshots = []
    exports = []
    harness.controller.devices = lambda: DeviceReadiness(microphone=True, playback=True)
    for session in sessions:
        harness.controller.start(session)
        harness.runner.submit(AUDIO)
        harness.controller.stop()
        snapshots.append(dataclasses.astuple(harness.results[0]))
        exports.append(format_transcript_v2(DE_ZH, harness.results))

    first = harness.results[0]
    assert [(r.source_language, r.target_language) for r in harness.results] == [
        (DE, ZH),
        (ZH, DE),
        (ZH, DE),
        (QAB, QAA),
    ]
    assert snapshots == [dataclasses.astuple(first)] * len(sessions)
    direction = f"[{first.captured_at.isoformat(timespec='seconds')}] de -> zh-Hans"
    for export in exports:
        lines = export.splitlines()
        assert lines[0] == "# lianiq transcript v2"
        assert lines[2:5] == [direction, "de: Guten Tag", "zh-Hans: [de>zh-Hans] Guten Tag"]
    last = harness.results[-1]
    assert exports[-1].splitlines()[-3:] == [
        f"[{last.captured_at.isoformat(timespec='seconds')}] qab -> qaa",
        "qab: beta",
        "qaa: [qab>qaa] beta",
    ]


def test_ac13_change_raises_pair_locked_error_while_running_and_not_after_stop(tmp_path) -> None:
    """AC-13 unit: the session pair, routing and output are locked until Stop."""
    harness = Harness(tmp_path, ScriptedRecognizer([]), voices=(DE, ZH))
    running = SessionPair(QAA_QAB, MICROPHONE_TEXT)
    harness.controller.start(running)
    other_pair = AUTOMATIC
    other_routing = SessionPair(QAA_QAB, fixed(DE).mode, fixed_source=QAA)
    other_output = SessionPair(
        QAA_QAB,
        UsageMode(InputKind.MICROPHONE, RoutingKind.BIDIRECTIONAL, OutputKind.SPOKEN),
    )

    for candidate in (other_pair, other_routing, other_output, running):
        with pytest.raises(PairLockedError, match="Stop the session to change"):
            harness.controller.change(candidate)
    assert harness.controller.session == running
    assert harness.controller.running

    harness.controller.stop()
    harness.controller.change(other_pair)
    assert harness.controller.session == other_pair
    assert not harness.controller.running
