from __future__ import annotations

import numpy as np


def convert_capture_audio(
    samples: np.ndarray,
    source_rate: int,
    target_rate: int = 16_000,
) -> np.ndarray:
    if source_rate <= 0 or target_rate <= 0:
        raise ValueError("sample rates must be positive")
    values = np.asarray(samples, dtype=np.float32)
    if values.ndim == 2:
        if values.shape[1] == 0:
            return np.empty(0, dtype=np.float32)
        values = np.mean(values, axis=1, dtype=np.float32)
    elif values.ndim != 1:
        raise ValueError("audio must be mono or frames-by-channels")
    values = np.clip(values.reshape(-1), -1.0, 1.0).astype(np.float32, copy=False)
    if values.size <= 1 or source_rate == target_rate:
        return values.copy()
    target_length = max(1, round(values.size * target_rate / source_rate))
    source_positions = np.arange(values.size, dtype=np.float64)
    target_positions = np.linspace(0, values.size - 1, target_length)
    converted = np.interp(target_positions, source_positions, values)
    return np.clip(converted, -1.0, 1.0).astype(np.float32)
