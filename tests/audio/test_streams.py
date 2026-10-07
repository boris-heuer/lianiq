from __future__ import annotations

import threading
from pathlib import Path

import numpy as np

from lianiq.audio.capture_stream import EndpointCaptureStream
from lianiq.audio.playback_stream import EndpointPlaybackStream
from lianiq.call_bridge.contracts import AudioEndpointRef, EndpointFlow
from lianiq.config import AudioConfig


def endpoint(flow: EndpointFlow) -> AudioEndpointRef:
    return AudioEndpointRef("stable", "Cable", flow, "Windows WASAPI", 7, 2, 48_000)


def test_capture_uses_explicit_endpoint_and_processes_audio_outside_callback() -> None:
    created = {}
    utterances = []
    received = threading.Event()

    class FakeStream:
        def __init__(self, **kwargs):
            created.update(kwargs)

        def start(self):
            return None

        def stop(self):
            return None

        def close(self):
            return None

    config = AudioConfig(
        chunk_ms=30,
        start_rms=0.02,
        end_silence_ms=90,
        pre_roll_ms=60,
        min_speech_ms=60,
    )
    stream = EndpointCaptureStream(
        endpoint(EndpointFlow.CAPTURE),
        config,
        on_utterance=lambda item: (utterances.append(item), received.set()),
        stream_factory=FakeStream,
    )
    stream.start()
    callback = created["callback"]
    voiced = np.full((1_440, 2), 0.1, dtype=np.float32)
    silent = np.zeros((1_440, 2), dtype=np.float32)
    for frame in [voiced, voiced, silent, silent, silent]:
        callback(frame, len(frame), object(), None)
    assert received.wait(timeout=1.0)
    stream.stop()

    assert created["device"] == 7
    assert created["samplerate"] == 48_000
    assert created["channels"] == 2
    assert utterances[0].sample_rate == 16_000


def test_playback_never_uses_default_endpoint(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        "lianiq.audio.playback_stream.play_wav",
        lambda path, output_device: calls.append((path, output_device)),
    )
    playback = EndpointPlaybackStream(endpoint(EndpointFlow.RENDER))

    playback.play(Path("probe.wav"))

    assert calls == [(Path("probe.wav"), 7)]
