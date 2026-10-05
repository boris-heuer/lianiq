from __future__ import annotations

import wave

import numpy as np
import pytest

from offline_translator.audio.wav import read_pcm16_mono


def write_wav(path, samples: np.ndarray, sample_rate: int, channels: int = 1) -> None:
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(samples.astype(np.int16).tobytes())


def test_read_pcm16_mono_resamples_to_target_rate(tmp_path) -> None:
    path = tmp_path / "input.wav"
    write_wav(path, np.array([0, 8_192, -8_192, 0], dtype=np.int16), 8_000)

    utterance = read_pcm16_mono(path, target_rate=16_000)

    assert utterance.sample_rate == 16_000
    assert utterance.samples.dtype == np.float32
    assert len(utterance.samples) == 8
    assert np.max(np.abs(utterance.samples)) <= 1.0


def test_read_pcm16_mono_rejects_stereo(tmp_path) -> None:
    path = tmp_path / "stereo.wav"
    write_wav(path, np.zeros(8, dtype=np.int16), 16_000, channels=2)

    with pytest.raises(ValueError, match="mono PCM16"):
        read_pcm16_mono(path)
