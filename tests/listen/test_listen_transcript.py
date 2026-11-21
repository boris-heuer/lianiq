"""CAP-0170 contract §3: rows, states, stale rule and export (AC-07, AC-08, AC-16, AC-17)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from lianiq.domain import TranslationResult
from lianiq.listen.session import listen_session
from lianiq.listen.transcript import ListenTranscript, SegmentState
from lianiq.pipeline_types import FailureReason
from tests.text_translation._text_helpers import DE, ZH, three_language_registry

PAIR = three_language_registry().pair(DE, ZH)
T0 = datetime(2026, 11, 21, 12, 0, tzinfo=UTC)


def result(turn_id, at, source, target, text="x", out="y") -> TranslationResult:
    return TranslationResult(turn_id, at, text, out, source, target, 0.1, 0.1)


def test_rows_keep_capture_order_and_states() -> None:
    transcript = ListenTranscript()
    first, second = uuid4(), uuid4()
    transcript.captured(second, T0 + timedelta(seconds=5), listen_session(PAIR, DE), 1)
    assert transcript.captured(first, T0, listen_session(PAIR, DE), 1) == 0
    assert transcript.recognized(first, "  ") == 0
    assert transcript.recognized(second, "Guten Morgen") == 1
    states = [row.state for row in transcript.rows]
    assert states == [SegmentState.NOT_UNDERSTOOD, SegmentState.TRANSLATING]
    assert transcript.mark(second, SegmentState.FAILED, FailureReason.MODEL) == 1
    assert transcript.rows[1].reason is FailureReason.MODEL


def test_unknown_and_finished_session_updates_are_ignored() -> None:
    transcript = ListenTranscript()
    turn, late = uuid4(), uuid4()
    transcript.captured(turn, T0, listen_session(PAIR, DE), 1)
    assert transcript.recognized(uuid4(), "x") is None
    assert transcript.finish_session(1) == 1
    assert transcript.rows[0].state is SegmentState.NOT_FINISHED
    assert transcript.completed(result(turn, T0, DE, ZH)) is None
    transcript.captured(late, T0 + timedelta(seconds=1), listen_session(PAIR, DE), 2)
    assert transcript.completed(result(late, T0, DE, ZH)) == 1


def test_export_has_only_done_rows_with_their_own_language_ids() -> None:
    transcript = ListenTranscript()
    de_turn, zh_turn, skipped = uuid4(), uuid4(), uuid4()
    transcript.captured(de_turn, T0, listen_session(PAIR, DE), 1)
    transcript.captured(skipped, T0 + timedelta(seconds=1), listen_session(PAIR, DE), 1)
    transcript.captured(zh_turn, T0 + timedelta(seconds=2), listen_session(PAIR, ZH), 2)
    transcript.completed(result(de_turn, T0, DE, ZH, "Hallo", "你好"))
    transcript.mark(skipped, SegmentState.SKIPPED)
    later = T0 + timedelta(seconds=2)
    transcript.completed(result(zh_turn, later, ZH, DE, "你好", "Hallo"))
    text = transcript.transcript_text(PAIR)
    assert "] de -> zh-Hans" in text and "] zh-Hans -> de" in text
    assert len(transcript.results()) == 2 and text.count("] ") == 2
