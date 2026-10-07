from __future__ import annotations

import wave
from pathlib import Path

import numpy as np


def play_wav(path: Path, output_device: int | None = None) -> None:
    try:
        import sounddevice as sd
    except ImportError as exc:
        raise RuntimeError("sounddevice is not installed") from exc
    with wave.open(str(path), "rb") as wav:
        channels = wav.getnchannels()
        sample_width = wav.getsampwidth()
        sample_rate = wav.getframerate()
        frames = wav.readframes(wav.getnframes())
    if sample_width != 2:
        raise RuntimeError(f"Unsupported WAV sample width: {sample_width * 8} bit")
    audio = np.frombuffer(frames, dtype=np.int16)
    if channels > 1:
        audio = audio.reshape(-1, channels)
    sd.play(audio, sample_rate, device=output_device, blocking=True)
