from __future__ import annotations

from pathlib import Path

from offline_translator.audio.playback import play_wav
from offline_translator.call_bridge.contracts import AudioEndpointRef, EndpointFlow


class EndpointPlaybackStream:
    """Playback adapter that can only target one explicit render endpoint."""

    def __init__(self, endpoint: AudioEndpointRef) -> None:
        if endpoint.flow is not EndpointFlow.RENDER:
            raise ValueError("EndpointPlaybackStream requires a render endpoint")
        self.endpoint = endpoint

    def rebind(self, endpoint: AudioEndpointRef) -> None:
        if endpoint.endpoint_id != self.endpoint.endpoint_id:
            raise ValueError("Recovered endpoint identity does not match configured endpoint")
        self.endpoint = endpoint

    def play(self, path: Path | str) -> None:
        play_wav(Path(path), self.endpoint.runtime_index)
