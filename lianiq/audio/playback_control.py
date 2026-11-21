"""Interruptible in-memory PCM playback (CAP-0172 contract.md §7).

``play_pcm`` blocks until the audio ends; the Text translation page must stop within 300 ms,
so this writes 50 ms blocks to a ``sounddevice.OutputStream`` and checks ``stop`` between
them. Device handling matches ``play_wav(…, auto_convert=True)`` (the Conversation output):
WASAPI shared-mode conversion on an explicit index, and a device that rejects the rate gets
the audio resampled to its own rate by ``resampler.py``.
"""

from __future__ import annotations

import threading

import numpy as np

from lianiq.audio.resampler import convert_capture_audio

BLOCK_SECONDS = 0.05


def play_pcm_interruptible(
    samples: np.ndarray, sample_rate: int, device: int | None, stop: threading.Event
) -> bool:
    """Play 16-bit PCM (frames or frames-by-channels); ``False`` when ``stop`` ended it early."""
    try:
        import sounddevice as sd
    except ImportError as exc:
        raise RuntimeError("sounddevice is not installed") from exc
    audio = np.asarray(samples, dtype=np.int16)
    if audio.ndim == 1:
        audio = audio.reshape(-1, 1)
    if device is None:
        return _write(sd, audio, sample_rate, None, None, stop)
    try:
        settings = sd.WasapiSettings(auto_convert=True)
        return _write(sd, audio, sample_rate, device, settings, stop)
    except sd.PortAudioError:
        rate = round(float(sd.query_devices(device)["default_samplerate"]))
        converted = convert_capture_audio(audio.astype(np.float32) / 32768.0, sample_rate, rate)
        return _write(sd, converted.reshape(-1, 1), rate, device, None, stop)


def _write(sd, audio: np.ndarray, rate: int, device, settings, stop: threading.Event) -> bool:
    block = max(1, int(rate * BLOCK_SECONDS))
    with sd.OutputStream(
        samplerate=rate,
        channels=audio.shape[1],
        dtype=audio.dtype.name,
        device=device,
        extra_settings=settings,
    ) as stream:
        for start in range(0, len(audio), block):
            if stop.is_set():
                stream.abort()
                return False
            stream.write(np.ascontiguousarray(audio[start : start + block]))
    return not stop.is_set()
