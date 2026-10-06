from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True, slots=True)
class BufferedAudio:
    samples: np.ndarray
    timestamp: float


@dataclass(slots=True)
class _Block:
    samples: np.ndarray
    timestamp: float


class AudioRingBuffer:
    """Thread-safe bounded PCM buffer that drops oldest samples on overrun."""

    def __init__(self, capacity_samples: int, sample_rate: int) -> None:
        if capacity_samples <= 0 or sample_rate <= 0:
            raise ValueError("capacity_samples and sample_rate must be positive")
        self.capacity_samples = capacity_samples
        self.sample_rate = sample_rate
        self._blocks: deque[_Block] = deque()
        self._size = 0
        self._lock = threading.Lock()
        self.overrun_samples = 0
        self.underruns = 0

    @property
    def size(self) -> int:
        with self._lock:
            return self._size

    def write(self, samples: np.ndarray, timestamp: float) -> int:
        values = np.asarray(samples, dtype=np.float32).reshape(-1).copy()
        if not values.size:
            return 0
        dropped = 0
        with self._lock:
            if values.size > self.capacity_samples:
                excess = values.size - self.capacity_samples
                values = values[excess:]
                timestamp += excess / self.sample_rate
                dropped += excess
            self._blocks.append(_Block(values, timestamp))
            self._size += values.size
            while self._size > self.capacity_samples:
                excess = self._size - self.capacity_samples
                block = self._blocks[0]
                if block.samples.size <= excess:
                    removed = block.samples.size
                    self._blocks.popleft()
                else:
                    removed = excess
                    block.samples = block.samples[removed:]
                    block.timestamp += removed / self.sample_rate
                self._size -= removed
                dropped += removed
            self.overrun_samples += dropped
        return dropped

    def read(self, max_samples: int) -> BufferedAudio | None:
        if max_samples <= 0:
            raise ValueError("max_samples must be positive")
        with self._lock:
            if not self._blocks:
                self.underruns += 1
                return None
            count = min(max_samples, self._size)
            timestamp = self._blocks[0].timestamp
            parts: list[np.ndarray] = []
            remaining = count
            while remaining:
                block = self._blocks[0]
                take = min(remaining, block.samples.size)
                parts.append(block.samples[:take])
                if take == block.samples.size:
                    self._blocks.popleft()
                else:
                    block.samples = block.samples[take:]
                    block.timestamp += take / self.sample_rate
                self._size -= take
                remaining -= take
            return BufferedAudio(np.concatenate(parts).astype(np.float32, copy=False), timestamp)
