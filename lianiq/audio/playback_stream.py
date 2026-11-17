from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import numpy as np

from lianiq.audio.playback import play_pcm, play_wav
from lianiq.call_bridge.contracts import AudioEndpointRef, EndpointFlow


class EndpointPlaybackStream:
    """Playback adapter that can only target one explicit render endpoint.

    The optional ``on_playback_state`` (CAP-0177 feedback guard) is called with ``True``
    right before the audio starts and with ``False`` after it ended, also when playback
    failed. Without it playback is unchanged (Call Bridge). ``play_pcm`` plays in-memory
    PCM16 on the same endpoint, so the meeting never writes an audio file.
    """

    def __init__(
        self,
        endpoint: AudioEndpointRef,
        *,
        on_playback_state: Callable[[bool], None] | None = None,
    ) -> None:
        if endpoint.flow is not EndpointFlow.RENDER:
            raise ValueError("EndpointPlaybackStream requires a render endpoint")
        self.endpoint = endpoint
        self.on_playback_state = on_playback_state

    def rebind(self, endpoint: AudioEndpointRef) -> None:
        if endpoint.endpoint_id != self.endpoint.endpoint_id:
            raise ValueError("Recovered endpoint identity does not match configured endpoint")
        self.endpoint = endpoint

    def play(self, path: Path | str) -> None:
        self._notify_around(lambda: play_wav(Path(path), self.endpoint.runtime_index))

    def play_pcm(self, samples: np.ndarray, sample_rate: int) -> None:
        self._notify_around(lambda: play_pcm(samples, sample_rate, self.endpoint.runtime_index))

    def _notify_around(self, playback: Callable[[], None]) -> None:
        notify = self.on_playback_state
        if notify is None:
            playback()
            return
        notify(True)
        try:
            playback()
        finally:
            notify(False)
