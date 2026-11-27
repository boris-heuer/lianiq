"""Spoken output of Conversation: speak after the result, replay and stop (CAP-0167 C §4).

Qt-free. The status, plan and Start-check rules live in ``voice_status.py`` and are
re-exported here. ``SpokenOutput.speak`` runs on the ``PipelineRunner`` worker (or the
held-turn resolution thread) after the result was delivered; ``replay`` runs on one daemon
thread. One playback lock serialises them, so playbacks never overlap, and every playback
has its own cancel flag: a translation that is still synthesizing when it is stopped is
never played. Logs carry the language ID, option values, state and error class only.
Per-turn **Replay** of a transcript row is ``SpokenReplay.replay_turn`` (paired-transcript
§3.3); every state change reaches each subscriber, the constructor ``on_state`` first.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from pathlib import Path

from lianiq.conversation.spoken_replay import PlaybackState, SpokenReplay
from lianiq.conversation.voice_status import (
    VOICE_NAME_SPEAKER,
    VoiceState,
    VoiceStatus,
    conversation_output,
    output_languages,
    spoken_plan,
    spoken_requirements,
    spoken_session,
    start_check,
    voice_status,
)
from lianiq.domain import TranslationResult
from lianiq.languages.registry import LanguageId
from lianiq.pipeline_types import PipelineEvent, PipelineEventKind
from lianiq.tts.voice_controls import VoiceOptions

__all__ = [
    "VOICE_NAME_SPEAKER",
    "PlaybackState",
    "SpokenOutput",
    "VoiceState",
    "VoiceStatus",
    "conversation_output",
    "output_languages",
    "spoken_plan",
    "spoken_requirements",
    "spoken_session",
    "start_check",
    "voice_status",
]

LOGGER = logging.getLogger(__name__)
CLOSE_WAIT_SECONDS = 1.0
REPLAY_THREAD = "spoken-output-replay"


class SpokenOutput(SpokenReplay):
    """Synthesizes and plays translations of the languages in the plan bound at Start.

    ``synthesizer`` returns the voice router (constructed on first use); ``bound`` applies
    the current ``options`` per playback. ``stop`` ends a blocking ``play`` from another
    thread (``lianiq.audio.playback.stop_playback``).
    """

    def __init__(
        self,
        synthesizer: Callable[[], object],
        play: Callable[[Path, int | None], None],
        stop: Callable[[], None],
        options: Callable[[LanguageId], VoiceOptions],
        on_state: Callable[[PlaybackState], None],
        on_event: Callable[[PipelineEvent], None],
    ) -> None:
        self._synthesizer = synthesizer
        self._play = play
        self._stop = stop
        self._options = options
        self._on_state = on_state  # the first subscriber
        self._subscribers: list[Callable[[PlaybackState], None]] = []
        self._on_event = on_event
        self._playback_lock = threading.Lock()  # one playback at a time
        self._guard = threading.Lock()  # the fields below; never held while waiting
        self._plan: frozenset[LanguageId] = frozenset()
        self._device: int | None = None
        self._closed = False
        self._cancel: threading.Event | None = None
        self._last: TranslationResult | None = None
        self._state = PlaybackState.IDLE
        self._replay: threading.Thread | None = None  # the running per-turn replay

    @property
    def plan(self) -> frozenset[LanguageId]:
        return self._plan

    @property
    def last_spoken(self) -> TranslationResult | None:
        return self._last

    @property
    def state(self) -> PlaybackState:
        return self._state

    def open(self, plan: frozenset[LanguageId], output_device: int | None) -> None:
        """Bind the spoken plan and the speakers of a starting session."""
        with self._guard:
            self._plan = frozenset(plan)
            self._device = output_device
            self._closed = False
        LOGGER.info("Spoken output opened: plan=%s", ",".join(sorted(plan)) or "-")

    def clear_plan(self) -> None:
        """The speakers were lost: the session continues text-only."""
        with self._guard:
            self._plan = frozenset()

    def speak(self, result: TranslationResult) -> None:
        """Speak ``result`` on the caller's thread; a language off the plan is not spoken."""
        with self._guard:
            if self._closed or result.target_language not in self._plan:
                return
            self._last = result
        self._playback(result.translated_text, result.target_language)

    def replay(self) -> threading.Thread | None:
        """Synthesize the last spoken translation again with the current options."""
        with self._guard:
            last = self._last
            if self._closed or last is None or last.target_language not in self._plan:
                return None
        thread = threading.Thread(
            target=self._playback,
            args=(last.translated_text, last.target_language),
            name=REPLAY_THREAD,
            daemon=True,
        )
        thread.start()
        return thread

    def stop_playback(self) -> None:
        """End the current synthesis or playback; a stopped synthesis is never played."""
        with self._guard:
            cancel = self._cancel
            if cancel is None:
                return
            cancel.set()
        LOGGER.info("Spoken output stopped: state=%s", self._state.value)
        self._stop()

    def close(self) -> None:
        """Session stop: nothing is spoken any more; waits at most 1 s for a playback."""
        with self._guard:
            self._closed = True
            cancel = self._cancel
            if cancel is not None:
                cancel.set()
        if cancel is not None:  # ``stop`` is global: only end this output's own playback
            self._stop()
        if self._playback_lock.acquire(timeout=CLOSE_WAIT_SECONDS):
            self._playback_lock.release()
        else:
            LOGGER.warning("Spoken output did not stop within %.1f seconds", CLOSE_WAIT_SECONDS)
        with self._guard:
            self._last = None
            self._plan = frozenset()

    def _set_state(self, state: PlaybackState) -> None:
        self._state = state
        for callback in (self._on_state, *self._subscribers):
            callback(state)

    def _playback(self, text: str, language: LanguageId) -> None:
        with self._playback_lock:
            cancel = threading.Event()
            with self._guard:
                if self._closed or language not in self._plan:
                    return
                self._cancel = cancel
                device = self._device
            path: Path | None = None
            try:
                self._set_state(PlaybackState.SYNTHESIZING)
                path = self._synthesize(text, language)
                if path is None:
                    return
                if not cancel.is_set() and not self._closed:
                    self._set_state(PlaybackState.PLAYING)
                # Checked again after entering PLAYING: a stop that arrived while ``on_state``
                # ran would find no stream to end yet, and the translation would play fully.
                if cancel.is_set() or self._closed:
                    LOGGER.info("Speech synthesis stopped before playback: language=%s", language)
                    return
                self._play_once(path, device, language, cancel)
            finally:
                if path is not None:
                    path.unlink(missing_ok=True)
                with self._guard:
                    if self._cancel is cancel:
                        self._cancel = None
                self._set_state(PlaybackState.IDLE)

    def _synthesize(self, text: str, language: LanguageId, on_event=None) -> Path | None:
        """The WAV of ``text``, or ``None`` after a reported synthesis failure."""
        started = time.perf_counter()
        options: VoiceOptions | None = None
        try:
            options = self._options(language)
            synthesizer = self._synthesizer()
            bound = getattr(synthesizer, "bound", None)
            voice = synthesizer if bound is None else bound({language: options})
            path = voice.synthesize(text, language)
        except Exception as exc:  # noqa: BLE001 - any engine failure keeps the text result
            LOGGER.warning(
                "Speech synthesis failed: language=%s options=%s error=%s",
                language,
                _options_text(options),
                type(exc).__name__,
            )
            (on_event or self._on_event)(
                PipelineEvent(
                    PipelineEventKind.SYNTHESIS_FAILED,
                    language=language,
                    message=type(exc).__name__,
                )
            )
            return None
        LOGGER.info(
            "Speech synthesis completed in %.3f seconds: language=%s options=%s",
            time.perf_counter() - started,
            language,
            _options_text(options),
        )
        return path

    def _play_once(
        self,
        path: Path,
        device: int | None,
        language: LanguageId,
        cancel: threading.Event,
        on_event=None,  # a replay's: its failure keeps the plan
    ) -> None:
        try:
            self._play(path, device)
        except Exception as exc:  # noqa: BLE001 - a playback failure is a notice event
            if cancel.is_set():
                LOGGER.info("Audio playback ended by a stop: language=%s", language)
                return
            LOGGER.warning(
                "Audio playback failed: language=%s error=%s", language, type(exc).__name__
            )
            if on_event is None:
                self.clear_plan()  # the speakers failed: the session continues text-only
            (on_event or self._on_event)(
                PipelineEvent(
                    PipelineEventKind.PLAYBACK_FAILED,
                    language=language,
                    message=type(exc).__name__,
                )
            )
            return
        LOGGER.info(
            "Audio playback %s: language=%s",
            "stopped" if cancel.is_set() else "completed",
            language,
        )


def _options_text(options: VoiceOptions | None) -> str:
    if options is None:
        return "-"
    speaker = "-" if options.speaker is None else str(options.speaker)
    return f"speaker={speaker} rate={options.rate:.2f} volume={options.volume:.2f}"
