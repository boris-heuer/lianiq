"""Worker callbacks of ``ListenController``, run on the GUI thread (file-size split).

Each callback carries the generation it was bound to; a stale one is dropped. A row of a
session that was cleared is ignored by the turn log itself (paired-transcript spec §2.2.2).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from lianiq.conversation.spoken_output import PlaybackState
from lianiq.listen.lifecycle import ListenPhase, quietly
from lianiq.pipeline_types import BoundUtterance, PipelineEvent, PipelineEventKind
from lianiq.transcript.turns import TurnState

if TYPE_CHECKING:
    from lianiq.domain import TranslationResult


class ListenCallbacks:
    """``ListenController`` base: ``_generation``, ``_phase``, ``_transcript``, ``render``."""

    def _current(self, generation: int) -> bool:
        return generation == self._generation and self._phase is not ListenPhase.IDLE

    def _captured(self, generation: int, item: BoundUtterance) -> None:
        if self._current(generation):
            row = self._transcript.captured(
                item.turn_id, item.captured_at, item.session, generation
            )
            self._changed(row)

    def _recognized(self, generation: int, item: BoundUtterance, text: str) -> None:
        if self._current(generation):
            self._changed(self._transcript.recognized(item.turn_id, text))

    def _completed(self, generation: int, result: TranslationResult) -> None:
        if self._current(generation):
            self._changed(self._transcript.completed(result))

    def _event(self, generation: int, event: PipelineEvent) -> None:
        if not self._current(generation):
            return
        if event.kind is PipelineEventKind.QUEUE_OVERFLOW and event.turn_id is not None:
            self._changed(self._transcript.mark(event.turn_id, TurnState.SKIPPED))
        elif event.kind is PipelineEventKind.TURN_FAILED and event.turn_id is not None:
            self._changed(self._transcript.mark(event.turn_id, TurnState.FAILED, event.failure))
        elif event.kind is PipelineEventKind.TURNS_DROPPED:
            rows = [self._transcript.mark(turn, TurnState.NOT_FINISHED) for turn in event.turn_ids]
            self.render(tuple(row for row in rows if row is not None))

    def _set_busy(self, generation: int, busy: bool) -> None:
        if self._current(generation):
            self._busy = busy
            self.render()

    def _changed(self, row: int | None) -> None:
        self.render(() if row is None else (row,))

    def playback_changed(self, state: PlaybackState) -> None:
        """``SpokenOutput`` subscriber, on the speaking thread (paired-transcript §3.3).

        While listening the capture is muted at once, so no frame reaches the segmenter; the
        page then shows ``VOICE_MIC_PAUSED`` and level 0. At ``IDLE`` it is unmuted, which
        never starts a capture.
        """
        paused = state is not PlaybackState.IDLE
        capture = self._capture
        if capture is not None and (not paused or self._phase is ListenPhase.LISTENING):
            quietly(lambda: capture.set_muted(paused), "mute")
        self._post(lambda: self._paused_changed(paused))

    def _paused_changed(self, paused: bool) -> None:
        if paused != self._paused:
            self._paused = paused
            self.render()
