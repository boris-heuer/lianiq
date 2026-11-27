"""The paired turn log (paired-transcript spec §3.1); Qt-free, GUI thread only, in memory only.

Moved from ``lianiq.listen.transcript`` (CAP-0170 contract.md §3) without behaviour change.
Rows are kept in capture order and never move. Every update names a ``turn_id``; an update
for an unknown turn or for a row of a finished session is ignored and returns ``None`` (the
stale-callback rule). Copy and Export contain only ``DONE`` rows. ``clear`` finishes every
session seen so far, so late callbacks of a cleared session never add or change a row.
"""

from __future__ import annotations

import bisect
from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from lianiq.domain import TranslationResult
from lianiq.languages.modes import SessionPair
from lianiq.languages.registry import LanguageId, LanguagePair, LanguageRegistry
from lianiq.languages.session import format_transcript_v2
from lianiq.pipeline_types import FailureReason


class TurnState(StrEnum):
    RECOGNIZING = "recognizing"
    TRANSLATING = "translating"
    DONE = "done"
    NOT_UNDERSTOOD = "not_understood"
    FAILED = "failed"
    SKIPPED = "skipped"
    NOT_FINISHED = "not_finished"


OPEN_STATES = frozenset({TurnState.RECOGNIZING, TurnState.TRANSLATING})


class TurnPart(StrEnum):
    ORIGINAL = "original"
    TRANSLATION = "translation"
    PAIR = "pair"


@dataclass(frozen=True, slots=True)
class Turn:
    turn_id: UUID
    captured_at: datetime
    session_id: int  # owner generation of the session that captured it
    source_language: LanguageId  # fixed at capture
    target_language: LanguageId
    state: TurnState
    source_text: str = ""  # in memory only
    result: TranslationResult | None = None
    reason: FailureReason | None = None

    @property
    def translated(self) -> bool:
        return self.state is TurnState.DONE and self.result is not None


class TurnLog:
    def __init__(self) -> None:
        self._rows: list[Turn] = []
        self._finished: set[int] = set()
        self._seen: set[int] = set()
        self._exported: set[UUID] = set()

    @property
    def rows(self) -> tuple[Turn, ...]:
        return tuple(self._rows)

    def __len__(self) -> int:
        return len(self._rows)

    def row(self, index: int) -> Turn:
        """One row without copying the log (the model reads rows one by one)."""
        return self._rows[index]

    def captured(
        self, turn_id: UUID, captured_at: datetime, session: SessionPair, session_id: int
    ) -> int | None:
        source = session.fixed_source
        target = session.fixed_target
        if source is None or target is None:
            raise ValueError("A listen segment needs a fixed-direction session")
        row = Turn(turn_id, captured_at, session_id, source, target, TurnState.RECOGNIZING)
        return self._insert(row)

    def add_result(self, result: TranslationResult, session_id: int) -> int | None:
        """A completed turn (Conversation) at its capture-time position; ``None`` if stale."""
        row = Turn(
            result.turn_id,
            result.captured_at,
            session_id,
            result.source_language,
            result.target_language,
            TurnState.DONE,
            result.source_text,
            result,
        )
        return self._insert(row)

    def recognized(self, turn_id: UUID, text: str) -> int | None:
        state = TurnState.TRANSLATING if text.strip() else TurnState.NOT_UNDERSTOOD
        return self._update(turn_id, state=state, source_text=text)

    def completed(self, result: TranslationResult) -> int | None:
        return self._update(
            result.turn_id,
            state=TurnState.DONE,
            source_text=result.source_text,
            result=result,
        )

    def mark(
        self, turn_id: UUID, state: TurnState, reason: FailureReason | None = None
    ) -> int | None:
        return self._update(turn_id, state=state, reason=reason)

    def finish_session(self, session_id: int) -> int:
        """Mark the session's open rows *not finished*; later updates for it are ignored."""
        count = 0
        for index, row in enumerate(self._rows):
            if row.session_id == session_id and row.state in OPEN_STATES:
                self._rows[index] = replace(row, state=TurnState.NOT_FINISHED)
                count += 1
        self._finished.add(session_id)
        return count

    def clear(self) -> int:
        """Remove every row and the export state; every session seen so far is finished."""
        removed = len(self._rows)
        self._finished |= self._seen
        self._rows.clear()
        self._exported.clear()
        return removed

    def results(self) -> tuple[TranslationResult, ...]:
        return tuple(row.result for row in self._rows if row.translated and row.result)

    def transcript_text(self, pair: LanguagePair) -> str:
        return format_transcript_v2(pair, self.results())

    def mark_exported(self, turn_ids: Iterable[UUID]) -> None:
        """The turns of the last successful export; they count as saved."""
        self._exported = set(turn_ids)

    def unsaved_count(self) -> int:
        return sum(1 for row in self._rows if row.translated and row.turn_id not in self._exported)

    def _insert(self, row: Turn) -> int | None:
        if row.session_id in self._finished:
            return None
        self._seen.add(row.session_id)
        index = bisect.bisect_right([item.captured_at for item in self._rows], row.captured_at)
        self._rows.insert(index, row)
        return index

    def _update(self, turn_id: UUID, **changes: object) -> int | None:
        for index, row in enumerate(self._rows):
            if row.turn_id == turn_id:
                if row.session_id in self._finished:
                    return None
                self._rows[index] = replace(row, **changes)
                return index
        return None


def turn_text(turn: Turn, part: TurnPart, registry: LanguageRegistry) -> str:
    """The text of one row for the clipboard (spec §2.2.1 step 3); never altered."""
    translation = turn.result.translated_text if turn.translated and turn.result else ""
    if part is TurnPart.ORIGINAL:
        return turn.source_text
    if part is TurnPart.TRANSLATION:
        return translation
    source = registry.display_name(turn.source_language)
    target = registry.display_name(turn.target_language)
    return f"{source}: {turn.source_text}\n{target}: {translation}"
