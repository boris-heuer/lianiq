"""CAP-0172 contract §7: interruptible PCM playback opens the device like ``play_wav``."""

from __future__ import annotations

import threading

import numpy as np

from lianiq.audio.playback_control import BLOCK_SECONDS, play_pcm_interruptible
from tests.audio.test_device_opening import fake_sounddevice, wav_file


def with_output_stream(sd, *, reject_auto_convert: bool = False, on_write=None):
    sd.streams = []

    class OutputStream:
        def __init__(self, **kwargs):
            if reject_auto_convert and kwargs.get("extra_settings") is not None:
                raise sd.PortAudioError("Invalid sample rate")
            self.kwargs, self.blocks, self.aborted = kwargs, [], False
            sd.streams.append(self)

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def write(self, block):
            self.blocks.append(block)
            if on_write is not None:
                on_write(len(self.blocks))

        def abort(self):
            self.aborted = True

    sd.OutputStream = OutputStream
    return sd


def tone(rate: int = 22_050, seconds: float = 0.5) -> np.ndarray:
    return np.zeros(int(rate * seconds), dtype=np.int16)


def test_the_stream_uses_the_same_index_and_auto_convert_as_play_wav(monkeypatch, tmp_path):
    from lianiq.audio.playback import play_wav

    sd = with_output_stream(fake_sounddevice(monkeypatch))
    play_wav(wav_file(tmp_path / "t.wav"), 7, auto_convert=True)
    wav_kwargs = sd.played[0][2]
    assert play_pcm_interruptible(tone(16_000), 16_000, 7, threading.Event()) is True
    stream = sd.streams[0]
    assert stream.kwargs["device"] == wav_kwargs["device"] == 7
    assert stream.kwargs["extra_settings"].auto_convert is wav_kwargs["extra_settings"].auto_convert
    assert stream.kwargs["samplerate"] == 16_000 and stream.kwargs["channels"] == 1
    assert len(stream.blocks) == round(0.5 / BLOCK_SECONDS)  # 50 ms blocks


def test_stop_ends_playback_at_the_next_block(monkeypatch):
    stop = threading.Event()
    sd = with_output_stream(
        fake_sounddevice(monkeypatch), on_write=lambda count: count == 2 and stop.set()
    )
    assert play_pcm_interruptible(tone(seconds=2.0), 22_050, 3, stop) is False
    assert len(sd.streams[0].blocks) == 2 and sd.streams[0].aborted


def test_a_device_rejecting_auto_convert_gets_resampled_audio(monkeypatch):
    sd = with_output_stream(fake_sounddevice(monkeypatch), reject_auto_convert=True)
    assert play_pcm_interruptible(tone(), 22_050, 3, threading.Event()) is True
    stream = sd.streams[0]
    assert stream.kwargs["samplerate"] == 48_000 and stream.kwargs["extra_settings"] is None
    assert stream.kwargs["dtype"] == "float32"
