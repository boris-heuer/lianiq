"""Listen transcript rows (CAP-0170 contract.md §3); GUI thread only, in memory only.

Rows are created in capture order and never move. Every update names a ``turn_id``; an
update for an unknown turn or for a row of a finished session is ignored and returns
``None`` (the stale-callback rule). Copy and Export contain only ``DONE`` rows.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from lianiq.domain import TranslationResult
from lianiq.languages.modes import SessionPair
from lianiq.languages.registry import LanguageId, LanguagePair
from lianiq.languages.session import format_transcript_v2
from lianiq.pipeline_types import FailureReason


class SegmentState(StrEnum):
    RECOGNIZING = "recognizing"
    TRANSLATING = "translating"
    DONE = "done"
    NOT_UNDERSTOOD = "not_understood"
    FAILED = "failed"
    SKIPPED = "skipped"
    NOT_FINISHED = "not_finished"


OPEN_STATES = frozenset({SegmentState.RECOGNIZING, SegmentState.TRANSLATING})


@dataclass(frozen=True, slots=True)
class Segment:
    turn_id: UUID
    captured_at: datetime
    session_id: int  # owner generation of the session that captured it
    source_language: LanguageId  # fixed at capture
    target_language: LanguageId
    state: SegmentState
    source_text: str = ""  # in memory only
    result: TranslationResult | None = None
    reason: FailureReason | None = None


class ListenTranscript:
    def __init__(self) -> None:
        self._rows: list[Segment] = []
        self._finished: set[int] = set()

    @property
    def rows(self) -> tuple[Segment, ...]:
        return tuple(self._rows)

    def captured(
        self, turn_id: UUID, captured_at: datetime, session: SessionPair, session_id: int
    ) -> int:
        source = session.fixed_source
        target = session.fixed_target
        if source is None or target is None:
            raise ValueError("A listen segment needs a fixed-direction session")
        row = Segment(turn_id, captured_at, session_id, source, target, SegmentState.RECOGNIZING)
        index = bisect.bisect_right([item.captured_at for item in self._rows], captured_at)
        self._rows.insert(index, row)
        return index

    def recognized(self, turn_id: UUID, text: str) -> int | None:
        state = SegmentState.TRANSLATING if text.strip() else SegmentState.NOT_UNDERSTOOD
        return self._update(turn_id, state=state, source_text=text)

    def completed(self, result: TranslationResult) -> int | None:
        return self._update(
            result.turn_id,
            state=SegmentState.DONE,
            source_text=result.source_text,
            result=result,
        )

    def mark(
        self, turn_id: UUID, state: SegmentState, reason: FailureReason | None = None
    ) -> int | None:
        return self._update(turn_id, state=state, reason=reason)

    def finish_session(self, session_id: int) -> int:
        """Mark the session's open rows *not finished*; later updates for it are ignored."""
        count = 0
        for index, row in enumerate(self._rows):
            if row.session_id == session_id and row.state in OPEN_STATES:
                self._rows[index] = replace(row, state=SegmentState.NOT_FINISHED)
                count += 1
        self._finished.add(session_id)
        return count

    def results(self) -> tuple[TranslationResult, ...]:
        return tuple(
            row.result
            for row in self._rows
            if row.state is SegmentState.DONE and row.result is not None
        )

    def transcript_text(self, pair: LanguagePair) -> str:
        return format_transcript_v2(pair, self.results())

    def _update(self, turn_id: UUID, **changes: object) -> int | None:
        for index, row in enumerate(self._rows):
            if row.turn_id == turn_id:
                if row.session_id in self._finished:
                    return None
                self._rows[index] = replace(row, **changes)
                return index
        return None
