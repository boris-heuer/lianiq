from __future__ import annotations

import numpy as np

from offline_translator.audio.segmenter import UtteranceSegmenter


def make_segmenter() -> UtteranceSegmenter:
    return UtteranceSegmenter(
        sample_rate=16_000,
        chunk_ms=30,
        start_rms=0.02,
        end_silence_ms=90,
        pre_roll_ms=60,
        min_speech_ms=60,
        max_speech_seconds=2.0,
    )


def frame(amplitude: float) -> np.ndarray:
    return np.full(480, amplitude, dtype=np.float32)


def test_segments_speech_after_silence() -> None:
    segmenter = make_segmenter()
    assert segmenter.push(frame(0.0)) is None
    assert segmenter.push(frame(0.1)) is None
    assert segmenter.push(frame(0.1)) is None
    assert segmenter.push(frame(0.0)) is None
    assert segmenter.push(frame(0.0)) is None
    result = segmenter.push(frame(0.0))
    assert result is not None
    assert result.dtype == np.float32
    assert len(result) == 6 * 480
    assert not segmenter.speaking


def test_ignores_short_noise_burst() -> None:
    segmenter = make_segmenter()
    segmenter.push(frame(0.1))
    segmenter.push(frame(0.0))
    segmenter.push(frame(0.0))
    assert segmenter.push(frame(0.0)) is None
    assert not segmenter.speaking


def test_flush_returns_active_utterance() -> None:
    segmenter = make_segmenter()
    segmenter.push(frame(0.1))
    segmenter.push(frame(0.1))
    result = segmenter.flush()
    assert result is not None
