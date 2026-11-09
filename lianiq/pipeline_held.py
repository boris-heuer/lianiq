"""Held-turn resolution and discard of ``TranslationPipeline`` (from ``pipeline.py``)."""

from __future__ import annotations

import logging
import time

from lianiq.conversation.routing import HeldTurn, TurnRoute
from lianiq.domain import TranslationResult
from lianiq.languages.errors import UnsupportedModeError
from lianiq.languages.registry import LanguageId
from lianiq.pipeline_types import _captured_at

# The ``lianiq.pipeline`` logger, as before the move.
LOGGER = logging.getLogger("lianiq.pipeline")


class PipelineHeldTurns:
    """``TranslationPipeline`` base: held turns keep their audio until resolved or dropped."""

    def resolve(self, held: HeldTurn, source: LanguageId) -> TranslationResult | None:
        """Translate a held turn as ``source`` by forced re-recognition of its retained audio.

        Detection never runs again. The result keeps the held turn's ID and capture time.
        The turn is claimed before any model runs, so it can no longer be discarded while
        it is resolved; its audio is released when it is translated. On failure the turn
        is held again.

        The context epoch is taken when the turn is claimed. If the session stops (context
        reset or held-turn discard) before the resolution reaches translation, the
        resolution is dropped: it returns ``None``, its audio is released and nothing is
        translated, exactly like an unresolved held turn at **Stop**.
        """
        with self._held_lock:
            retained = self._held.get(held.turn_id)
            if retained is None:
                raise LookupError("The held turn is no longer pending")
            pair = retained.item.session.pair
            if source not in pair:
                raise UnsupportedModeError(f"{source!r} is not a member of the session pair")
            del self._held[held.turn_id]  # claimed: no longer held, not discardable
            claimed_epoch = self._epoch()
        item = retained.item
        try:
            with self._turn_lock:
                if self._epoch() != claimed_epoch:
                    LOGGER.info("The session stopped before the held turn was resolved; dropped")
                    return None
                epoch = claimed_epoch
                started = time.perf_counter()
                transcript = self.speech_recognizer().transcribe(
                    item.utterance.samples, item.utterance.sample_rate, source
                )
                stt_seconds = time.perf_counter() - started
                if self._epoch() != epoch:
                    LOGGER.info("The session stopped while the held turn was re-recognised")
                    return None
                if not transcript.text.strip():
                    LOGGER.info("Forced re-recognition returned no text; the turn was dropped")
                    return None
                return self._translate(
                    transcript.text,
                    TurnRoute(source, pair.other(source)),
                    stt_seconds,
                    item,
                    epoch,
                )
        except BaseException:
            with self._held_lock:
                # Held again only within its session; after Stop it is dropped with its audio.
                if self._epoch() == claimed_epoch:
                    self._held[held.turn_id] = retained
            raise

    def discard(self, held: HeldTurn) -> bool:
        """Drop a held turn and release its audio; it leaves no result and no export line.

        Returns ``False`` if the turn is no longer held (resolved, being resolved or
        already discarded).
        """
        with self._held_lock:
            return self._held.pop(held.turn_id, None) is not None

    def discard_held(self) -> tuple[HeldTurn, ...]:
        """Discard every unresolved held turn (session stop); returns them by capture time.

        This also ends the context epoch under the held-turn lock, so a resolution that
        claimed its turn before this call is dropped instead of surviving the stop.
        """
        with self._held_lock:
            discarded = self._sorted_held()
            self._held.clear()
            self._end_context_epoch()
        return discarded

    def held_turns(self) -> tuple[HeldTurn, ...]:
        """The unresolved held turns ordered by capture time."""
        with self._held_lock:
            return self._sorted_held()

    def _sorted_held(self) -> tuple[HeldTurn, ...]:
        return tuple(sorted((entry.held for entry in self._held.values()), key=_captured_at))
