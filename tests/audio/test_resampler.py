from __future__ import annotations

import numpy as np

from lianiq.audio.resampler import convert_capture_audio


def test_stereo_48khz_is_downmixed_and_resampled_to_mono_16khz() -> None:
    left = np.linspace(-2.0, 2.0, 480, dtype=np.float32)
    right = -left
    stereo = np.column_stack((left, right))

    converted = convert_capture_audio(stereo, 48_000, 16_000)

    assert converted.shape == (160,)
    assert converted.dtype == np.float32
    assert np.max(np.abs(converted)) <= 1.0
    assert np.allclose(converted, 0.0, atol=1e-6)


def test_empty_and_partial_frames_are_deterministic() -> None:
    assert convert_capture_audio(np.empty((0, 2)), 48_000, 16_000).size == 0
    result = convert_capture_audio(np.array([[0.5, 0.5]], dtype=np.float32), 48_000, 16_000)
    assert result.tolist() == [0.5]
