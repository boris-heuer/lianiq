from __future__ import annotations

import threading
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


class InferenceScheduler:
    """Bounds concurrent model work so audio callbacks remain independent."""

    def __init__(self, max_concurrent: int = 1) -> None:
        if max_concurrent <= 0:
            raise ValueError("max_concurrent must be positive")
        self._semaphore = threading.BoundedSemaphore(max_concurrent)
        self._lock = threading.Lock()
        self._active = 0

    @property
    def active(self) -> int:
        with self._lock:
            return self._active

    def run(self, operation: Callable[[], T]) -> T:
        with self._semaphore:
            with self._lock:
                self._active += 1
            try:
                return operation()
            finally:
                with self._lock:
                    self._active -= 1
