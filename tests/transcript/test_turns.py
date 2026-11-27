"""paired-transcript WI-01: the shared turn log (spec §3.1; AC-04, AC-11, AC-12, AC-13, AC-15)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from lianiq.domain import TranslationResult
from lianiq.listen.session import listen_session
from lianiq.listen.transcript import ListenTranscript, Segment, SegmentState
from lianiq.transcript import Turn, TurnLog, TurnPart, TurnState, turn_text
from tests.text_translation._text_helpers import DE, ZH, three_language_registry

REGISTRY = three_language_registry()
PAIR = REGISTRY.pair(DE, ZH)
T0 = datetime(2026, 11, 27, 9, 0, tzinfo=UTC)
RTL = "שלום עולם, مرحبا"
CJK = "你好，世界。\n第二行"
LATIN = "Grüße, Straße — ça va? é"


def result(at, text="Hallo", out="你好", source=DE, target=ZH) -> TranslationResult:
    return TranslationResult(uuid4(), at, text, out, source, target, 0.1, 0.1)


def test_old_listen_names_are_the_turn_log() -> None:
    assert ListenTranscript is TurnLog and Segment is Turn and SegmentState is TurnState


def test_add_result_lands_at_capture_time_and_counts_unsaved() -> None:
    log = TurnLog()
    late, early = result(T0 + timedelta(seconds=9)), result(T0)
    assert log.add_result(late, 1) == 0
    assert log.add_result(early, 1) == 0  # a held turn resolved later: at its capture time
    assert [row.turn_id for row in log.rows] == [early.turn_id, late.turn_id]
    assert log.unsaved_count() == 2
    log.mark_exported([early.turn_id])
    assert log.unsaved_count() == 1
    log.mark_exported(r.turn_id for r in log.results())
    assert log.unsaved_count() == 0


def test_clear_finishes_every_seen_session_so_late_updates_are_ignored() -> None:
    log = TurnLog()
    open_turn = uuid4()
    log.captured(open_turn, T0, listen_session(PAIR, DE), 3)
    log.add_result(result(T0), 4)
    log.mark_exported([])
    assert log.clear() == 2 and log.rows == () and log.unsaved_count() == 0
    # Late callbacks of the cleared sessions: nothing added or changed.
    assert log.captured(uuid4(), T0, listen_session(PAIR, DE), 3) is None
    assert log.add_result(result(T0), 4) is None
    assert log.recognized(open_turn, "spät") is None
    assert log.rows == ()
    # The next session's rows appear normally.
    assert log.add_result(result(T0), 5) == 0


def test_a_normal_finish_keeps_completed_rows_of_other_sessions() -> None:
    log = TurnLog()
    log.add_result(result(T0), 1)
    log.finish_session(2)
    assert log.add_result(result(T0 + timedelta(seconds=1)), 1) == 1


def test_turn_text_parts_and_pair_format() -> None:
    log = TurnLog()
    log.add_result(result(T0, "Guten Morgen.", "早上好。"), 1)
    turn = log.rows[0]
    assert turn_text(turn, TurnPart.ORIGINAL, REGISTRY) == "Guten Morgen."
    assert turn_text(turn, TurnPart.TRANSLATION, REGISTRY) == "早上好。"
    pair = turn_text(turn, TurnPart.PAIR, REGISTRY)
    assert pair == "German: Guten Morgen.\nMandarin (Simplified): 早上好。"


def test_untranslated_turn_has_only_its_original() -> None:
    log = TurnLog()
    turn_id = uuid4()
    log.captured(turn_id, T0, listen_session(PAIR, DE), 1)
    log.recognized(turn_id, "Hallo")
    turn = log.rows[0]
    assert not turn.translated and turn_text(turn, TurnPart.TRANSLATION, REGISTRY) == ""
    assert log.unsaved_count() == 0 and log.results() == ()


def test_rtl_cjk_and_diacritics_round_trip_unchanged(tmp_path) -> None:
    log = TurnLog()
    for offset, (text, out) in enumerate(((RTL, CJK), (LATIN, RTL), (CJK, LATIN))):
        log.add_result(result(T0 + timedelta(seconds=offset), text, out), 1)
    for row, (text, out) in zip(log.rows, ((RTL, CJK), (LATIN, RTL), (CJK, LATIN)), strict=True):
        assert turn_text(row, TurnPart.ORIGINAL, REGISTRY) == text
        assert turn_text(row, TurnPart.TRANSLATION, REGISTRY) == out
    path = tmp_path / "t.txt"
    path.write_text(log.transcript_text(PAIR), encoding="utf-8")
    written = path.read_text(encoding="utf-8")
    for fixture in (RTL, LATIN, *CJK.split("\n")):
        assert fixture in written
