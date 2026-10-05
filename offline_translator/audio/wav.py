from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

from offline_translator.domain import AudioUtterance


def read_pcm16_mono(path: Path, target_rate: int = 16_000) -> AudioUtterance:
    with wave.open(str(path), "rb") as wav_file:
        if wav_file.getnchannels() != 1 or wav_file.getsampwidth() != 2:
            raise ValueError(f"Expected mono PCM16 WAV: {path}")
        source_rate = wav_file.getframerate()
        samples = np.frombuffer(wav_file.readframes(wav_file.getnframes()), dtype=np.int16)

    float_samples = samples.astype(np.float32) / 32768.0
    if source_rate != target_rate and float_samples.size:
        old_positions = np.arange(len(float_samples), dtype=np.float64)
        new_positions = np.linspace(
            0,
            len(float_samples) - 1,
            round(len(float_samples) * target_rate / source_rate),
        )
        float_samples = np.interp(new_positions, old_positions, float_samples).astype(np.float32)
    return AudioUtterance(float_samples, target_rate)
