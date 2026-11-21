"""Play translation as an active session (CAP-0172 contract.md §7).

``TextPlayback.play`` takes the one session of ``ActiveSessionOwner`` for Text translation
(``SessionBusy`` while another mode holds it) and registers an asynchronous stopper, so F9
and the strip's **Stop (F9)** end it from every workspace. A worker synthesises the result's
sentences one by one in memory (``synthesize_pcm``, no file) for ``result.edge.target`` only
and plays each on the Conversation output index; ``stop`` is checked between and within
segments. Every state change and the outcome reach the GUI thread through ``post``.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import TYPE_CHECKING, Literal, Protocol

import numpy as np

from lianiq.audio.playback_control import play_pcm_interruptible
from lianiq.text_translation.jobs import FailureReason
from lianiq.ui.shell.workspaces import WorkspaceId

if TYPE_CHECKING:
    from lianiq.languages.registry import LanguageId
    from lianiq.text_translation.state import TextResult
    from lianiq.ui.shell.session_owner import ActiveSessionOwner

LOGGER = logging.getLogger(__name__)
TEXT_TRANSLATION = WorkspaceId.TEXT_TRANSLATION
PlaybackState = Literal["idle", "starting", "playing", "stopping"]


class PcmPlayer(Protocol):
    def play(
        self, samples: np.ndarray, sample_rate: int, device: int | None, stop: threading.Event
    ) -> bool: ...  # False when stopped early


class PcmVoice(Protocol):
    def synthesize_pcm(self, text: str, language: str) -> tuple[np.ndarray, int]: ...


class DevicePlayer:
    """The real ``PcmPlayer``: ``play_pcm_interruptible`` on the speakers."""

    def play(self, samples, sample_rate, device, stop) -> bool:
        return play_pcm_interruptible(samples, sample_rate, device, stop)


class _DeviceError(Exception):
    """The player failed: the speakers could not be opened or written."""


class TextPlayback:
    def __init__(
        self,
        owner: ActiveSessionOwner,
        voice: Callable[[LanguageId], PcmVoice],
        player: PcmPlayer,
        speakers: Callable[[], object],
        post: Callable[[Callable[[], None]], None],
    ) -> None:
        self.owner, self._voice, self.player = owner, voice, player
        self._speakers, self._post = speakers, post
        self.state: PlaybackState = "idle"
        self.playing: int | None = None  # result_id being played
        self.played: int | None = None  # last result_id played (the Replay label)
        self.on_change: Callable[[], None] = lambda: None
        self.on_failed: Callable[[FailureReason], None] = lambda _reason: None
        self._generation = 0
        self._stop: threading.Event | None = None
        owner.register(TEXT_TRANSLATION, self.stop, asynchronous=True)

    def play(self, result: TextResult) -> None:
        """**Play translation** / **Replay** from the start; raises ``SessionBusy``."""
        generation = self.owner.request_start(TEXT_TRANSLATION)
        stop = threading.Event()
        self._generation, self._stop = generation, stop
        self.playing, self.state = result.result_id, "starting"
        self.on_change()
        try:
            endpoint = getattr(self._speakers(), "endpoint", None)
            device = None if endpoint is None else endpoint.runtime_index
            voice = self._voice(result.edge.target)
        except Exception as error:  # noqa: BLE001 - mapped to a reason; never shown
            self._ended(generation, result.result_id, error)
            return
        threading.Thread(
            target=self._run,
            args=(generation, result, voice, device, stop),
            name="text-playback",
            daemon=True,
        ).start()

    def stop(self) -> None:
        """Stop, F9 or a stale result: ends within one 50 ms block; texts are untouched."""
        if self._stop is not None and self.state != "idle":
            self._stop.set()
            self.state = "stopping"
            self.on_change()

    def _run(self, generation, result, voice, device, stop: threading.Event) -> None:
        error: BaseException | None = None
        language = result.edge.target
        try:
            for index, segment in enumerate(result.segments):
                if stop.is_set():
                    break
                samples, rate = voice.synthesize_pcm(segment, language)
                if stop.is_set():
                    break
                if index == 0:
                    self._post(lambda: self._running(generation))
                try:
                    finished = self.player.play(samples, rate, device, stop)
                except Exception as exc:
                    raise _DeviceError from exc
                if not finished:
                    break
        except Exception as exc:  # noqa: BLE001 - mapped to a reason; never logged as text
            error = exc
        self._post(lambda: self._ended(generation, result.result_id, error))

    def _running(self, generation: int) -> None:
        if generation == self._generation and self.state == "starting":
            self.state = "playing"
            self.owner.mark_running(generation)
            self.on_change()

    def _ended(self, generation: int, result_id: int, error: BaseException | None) -> None:
        if generation != self._generation:
            return
        LOGGER.info(
            "Text playback ended: result=%d outcome=%s",
            result_id,
            "ok" if error is None else type(error.__cause__ or error).__name__,
        )
        self._stop, self.playing, self.played, self.state = None, None, result_id, "idle"
        self.owner.mark_idle(generation)
        self.on_change()
        if error is not None:
            device = isinstance(error, _DeviceError)
            self.on_failed(FailureReason.DEVICE if device else FailureReason.OTHER)
