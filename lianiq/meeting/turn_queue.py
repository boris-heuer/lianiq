"""No-drop turn queue across both meeting inputs (CAP-0177 contract.md §3).

Qt-free and thread-safe: both captures put, the single inference worker takes. Contributions
come out sorted by speech end (``ended_at``); equal ends keep their insertion order. There is
no age expiry and no capacity limit, unlike the Call Bridge lane queues. The soft limit only
drives the "falling behind" notice, which clears at or below the limit again.
"""

from __future__ import annotations

import bisect
import itertools
import threading
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from lianiq.domain import AudioUtterance
from lianiq.languages.registry import LanguageId
from lianiq.meeting.contracts import CAPTURE_ROLES, MeetingRole

TURN_QUEUE_SOFT_LIMIT = 6  # queued, not yet processed contributions


@dataclass(frozen=True, slots=True)
class Contribution:
    contribution_id: UUID
    role: MeetingRole  # TABLE_CAPTURE or USER_CAPTURE
    source_language: LanguageId
    target_language: LanguageId
    ended_at: datetime  # speech end; becomes TranslationResult.captured_at
    utterance: AudioUtterance  # released after STT

    def __post_init__(self) -> None:
        if self.role not in CAPTURE_ROLES:
            raise ValueError(f"A contribution comes from a capture role, not {self.role.value}")


class TurnQueue:
    def __init__(self) -> None:
        self._items: list[tuple[datetime, int, Contribution]] = []
        self._sequence = itertools.count()
        self._available = threading.Condition()

    def put(self, item: Contribution) -> None:
        """Sorted insert by ``ended_at``; never drops."""
        with self._available:
            entry = (item.ended_at, next(self._sequence), item)
            bisect.insort(self._items, entry, key=lambda queued: queued[:2])
            self._available.notify()

    def take(self, timeout: float | None = None) -> Contribution | None:
        """The earliest contribution, or ``None`` when none arrived within ``timeout``."""
        with self._available:
            if not self._available.wait_for(lambda: self._items, timeout):
                return None
            return self._items.pop(0)[2]

    def __len__(self) -> int:
        with self._available:
            return len(self._items)

    @property
    def falling_behind(self) -> bool:
        return len(self) > TURN_QUEUE_SOFT_LIMIT
