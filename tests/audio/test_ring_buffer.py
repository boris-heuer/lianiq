from __future__ import annotations

import numpy as np

from offline_translator.audio.ring_buffer import AudioRingBuffer


def test_partial_reads_preserve_timestamp() -> None:
    buffer = AudioRingBuffer(capacity_samples=8, sample_rate=4)
    buffer.write(np.array([1, 2, 3, 4], dtype=np.float32), timestamp=10.0)

    first = buffer.read(2)
    second = buffer.read(2)

    assert first is not None and first.timestamp == 10.0
    assert second is not None and second.timestamp == 10.5
    assert second.samples.tolist() == [3.0, 4.0]


def test_overrun_drops_oldest_samples_and_is_reported() -> None:
    buffer = AudioRingBuffer(capacity_samples=4, sample_rate=4)
    buffer.write(np.array([1, 2, 3], dtype=np.float32), timestamp=1.0)
    dropped = buffer.write(np.array([4, 5, 6], dtype=np.float32), timestamp=1.75)

    chunk = buffer.read(4)

    assert dropped == 2
    assert buffer.overrun_samples == 2
    assert chunk is not None and chunk.samples.tolist() == [3.0, 4.0, 5.0, 6.0]
    assert chunk.timestamp == 1.5


def test_underrun_is_counted_without_fabricating_audio() -> None:
    buffer = AudioRingBuffer(capacity_samples=4, sample_rate=4)
    assert buffer.read(2) is None
    assert buffer.underruns == 1
