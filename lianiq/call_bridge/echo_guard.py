"""Call Bridge echo guard (CAP-0166 spec §3.1, AC-12).

The inbound lane plays local-language speech into the headphones; a headset microphone can
pick it up. ``outbound_muted`` is true from the first ``playback_started`` until the last
``playback_finished`` plus ``guard_tail_ms``: the semantics of the CAP-0177 ``FeedbackGuard``
``mute`` policy for a local render that is not marked as a headset, without its meeting
roles. Muted outbound frames are discarded and the outbound segmenter is reset (the capture
side's job). Qt-free and thread-safe; time comes from the injected ``clock`` (seconds,
monotonic).
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable


class EchoGuard:
    def __init__(
        self, guard_tail_ms: int = 300, clock: Callable[[], float] = time.monotonic
    ) -> None:
        if guard_tail_ms < 0:
            raise ValueError("guard_tail_ms must not be negative")
        self._tail = guard_tail_ms / 1000.0
        self._clock = clock
        self._lock = threading.Lock()
        self._playing = 0
        self._tail_until: float | None = None

    def playback_started(self) -> None:
        with self._lock:
            self._playing += 1

    def playback_finished(self) -> None:
        """Ends one playback; the outbound capture stays muted for the guard tail."""
        now = self._clock()
        with self._lock:
            self._playing = max(0, self._playing - 1)
            if self._playing == 0:
                self._tail_until = now + self._tail

    def outbound_muted(self, now: float | None = None) -> bool:
        current = self._clock() if now is None else now
        with self._lock:
            if self._playing:
                return True
            return self._tail_until is not None and current < self._tail_until
