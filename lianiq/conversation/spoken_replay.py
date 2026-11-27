"""Per-turn **Replay** of a transcript row (paired-transcript spec §3.3); ``SpokenOutput`` base.

Qt-free. ``replay_turn`` has its own path: it skips the ``_closed`` and plan checks of
``_playback`` (a replay on an idle page after **Stop** is allowed), but it holds the same
playback lock, so it never overlaps a spoken turn or another replay, and it uses the same
cancel slot, so ``stop_playback`` and ``close`` end it and a stopped synthesis is never
played. It never changes ``last_spoken`` or the plan; a failure goes only to the caller's
``on_event``. The voice is constructed on the first synthesis, never before a click.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from enum import StrEnum
from pathlib import Path

from lianiq.domain import TranslationResult
from lianiq.pipeline_types import PipelineEvent

LOGGER = logging.getLogger("lianiq.conversation.spoken_output")
TURN_REPLAY_THREAD = "spoken-output-turn-replay"


class PlaybackState(StrEnum):
    IDLE = "idle"
    SYNTHESIZING = "synthesizing"
    PLAYING = "playing"


class SpokenReplay:
    """Subscribers and the per-turn replay; ``SpokenOutput`` provides the fields."""

    def subscribe(self, callback: Callable[[PlaybackState], None]) -> None:
        """``callback(state)`` on the speaking thread after each state change."""
        self._subscribers.append(callback)

    @property
    def active_replay(self) -> threading.Thread | None:
        """The thread of the per-turn replay that synthesizes or plays, else ``None``."""
        return self._replay

    def replay_turn(
        self,
        result: TranslationResult,
        output_device: int | None,
        on_event: Callable[[PipelineEvent], None],
    ) -> threading.Thread | None:
        """Speak ``result``'s translation on ``output_device``; ``None`` while one plays."""
        if not self._playback_lock.acquire(blocking=False):
            return None
        cancel = threading.Event()
        thread = threading.Thread(
            target=self._replay_body,
            args=(result, output_device, on_event, cancel),
            name=TURN_REPLAY_THREAD,
            daemon=True,
        )
        with self._guard:
            self._cancel, self._replay = cancel, thread
        try:
            thread.start()
        except BaseException:
            with self._guard:
                self._cancel = self._replay = None
            self._playback_lock.release()
            raise
        return thread

    def _replay_body(
        self,
        result: TranslationResult,
        device: int | None,
        on_event: Callable[[PipelineEvent], None],
        cancel: threading.Event,
    ) -> None:
        language = result.target_language
        path: Path | None = None
        try:
            self._set_state(PlaybackState.SYNTHESIZING)
            if cancel.is_set():
                return  # stopped before the synthesis began
            path = self._synthesize(result.translated_text, language, on_event)
            if path is None:
                return
            if not cancel.is_set():
                self._set_state(PlaybackState.PLAYING)
            if cancel.is_set():  # as in ``_playback``: a stop during ``on_state``
                LOGGER.info("Replay stopped before playback: language=%s", language)
                return
            self._play_once(path, device, language, cancel, on_event)
        finally:
            if path is not None:
                path.unlink(missing_ok=True)
            with self._guard:
                if self._cancel is cancel:
                    self._cancel = None
                self._replay = None
            try:
                self._set_state(PlaybackState.IDLE)
            finally:
                self._playback_lock.release()
