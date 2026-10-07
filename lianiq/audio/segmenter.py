from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

import numpy as np


@dataclass(slots=True)
class UtteranceSegmenter:
    sample_rate: int
    chunk_ms: int
    start_rms: float
    end_silence_ms: int
    pre_roll_ms: int
    min_speech_ms: int
    max_speech_seconds: float
    _speaking: bool = field(default=False, init=False)
    _frames: list[np.ndarray] = field(default_factory=list, init=False)
    _pre_roll: deque[np.ndarray] = field(init=False)
    _silence_ms: int = field(default=0, init=False)
    _speech_ms: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        if self.chunk_ms <= 0 or self.sample_rate <= 0:
            raise ValueError("sample_rate and chunk_ms must be positive")
        self._pre_roll = deque(maxlen=max(1, self.pre_roll_ms // self.chunk_ms))

    @property
    def speaking(self) -> bool:
        return self._speaking

    def reset(self) -> None:
        self._speaking = False
        self._frames.clear()
        self._pre_roll.clear()
        self._silence_ms = 0
        self._speech_ms = 0

    def push(self, frame: np.ndarray) -> np.ndarray | None:
        mono = np.asarray(frame, dtype=np.float32).reshape(-1).copy()
        if mono.size == 0:
            return None
        rms = float(np.sqrt(np.mean(np.square(mono), dtype=np.float64)))
        voiced = rms >= self.start_rms

        if not self._speaking:
            self._pre_roll.append(mono)
            if not voiced:
                return None
            self._speaking = True
            self._frames = list(self._pre_roll)
            self._pre_roll.clear()
            self._speech_ms = self.chunk_ms
            self._silence_ms = 0
            return None

        self._frames.append(mono)
        if voiced:
            self._speech_ms += self.chunk_ms
            self._silence_ms = 0
        else:
            self._silence_ms += self.chunk_ms

        elapsed_seconds = len(self._frames) * self.chunk_ms / 1000
        if self._silence_ms < self.end_silence_ms and elapsed_seconds < self.max_speech_seconds:
            return None

        result = np.concatenate(self._frames)
        valid = self._speech_ms >= self.min_speech_ms
        self.reset()
        return result if valid else None

    def flush(self) -> np.ndarray | None:
        if not self._speaking or self._speech_ms < self.min_speech_ms:
            self.reset()
            return None
        result = np.concatenate(self._frames)
        self.reset()
        return result
