"""Notices (CAP-0168 contract.md §3, ``lianiq.shell.notice-model.v1``).

Qt-free: a ``Notice`` says what failed (``title``), the next step (``detail``), which mode,
lane and language it concerns (``source``), whether recording and playback continue
(``continues``) and what the user can do (``actions``). ``NoticeCenter`` keeps one live
notice per key:

- a blocking notice is cleared only by its own ``resolve(key)``, never by unrelated success
  or a later info notice; a post with the key of a live blocking notice replaces it only
  when it is blocking too;
- a repeated post of a key updates that one notice and counts the repeat;
- an async producer passes the session generation it belongs to; a notice of an older
  generation than the current one is dropped;
- ``top`` is the highest severity, newest first.

``history`` keeps every accepted post in order (Settings › Diagnostics). Nothing here holds
transcript text: notice texts name what failed, never what was said.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from enum import IntEnum

from lianiq.ui.shell.workspaces import WorkspaceId

HISTORY_CAPACITY = 200


class Severity(IntEnum):
    INFO = 0
    WARNING = 1
    BLOCKING = 2


@dataclass(frozen=True)
class NoticeAction:
    label: str
    callback: Callable[[], None]
    # Optional: whether the action can run now, and the hint shown while it cannot
    # (e.g. **Reconnect** while a stream is open: ``DEVICE_RECONNECT_AFTER_STOP``).
    enabled: Callable[[], bool] | None = None
    disabled_hint: str = ""

    def available(self) -> bool:
        return self.enabled is None or bool(self.enabled())


@dataclass(frozen=True)
class Notice:
    key: str  # one live notice per key
    severity: Severity
    title: str  # what failed
    detail: str  # user-facing next step
    source: str  # mode / lane / language, e.g. "Conversation · German"
    continues: str  # e.g. "Recording stopped. Playback stopped."
    workspace: WorkspaceId
    actions: tuple[NoticeAction, ...] = ()
    generation: int | None = None
    repeats: int = field(default=0, compare=False)  # set by ``NoticeCenter``


# ``listener(change, notice)``: change is "posted" or "resolved".
Listener = Callable[[str, Notice], None]


class NoticeCenter:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._live: dict[str, tuple[Notice, float, int]] = {}
        self._sequence = 0  # breaks clock ties: a later post is newer
        self._history: deque[Notice] = deque(maxlen=HISTORY_CAPACITY)
        self._listeners: list[Listener] = []

    def post(self, notice: Notice, current_generation: int | None = None) -> bool:
        """Show ``notice``; ``False`` (nothing stored) for a stale generation or a weaker
        post over a live blocking notice of the same key."""
        if (
            notice.generation is not None
            and current_generation is not None
            and notice.generation < current_generation
        ):
            return False
        live = self._live.get(notice.key)
        if live is not None:
            previous = live[0]
            if previous.severity is Severity.BLOCKING and notice.severity is not Severity.BLOCKING:
                return False
            notice = replace(notice, repeats=previous.repeats + 1)
        else:
            notice = replace(notice, repeats=0)
        self._sequence += 1
        self._live[notice.key] = (notice, self._clock(), self._sequence)
        self._history.append(notice)
        self._notify("posted", notice)
        return True

    def resolve(self, key: str) -> None:
        """Clear the live notice ``key`` (its own condition is resolved); a no-op if absent."""
        live = self._live.pop(key, None)
        if live is not None:
            self._notify("resolved", live[0])

    def get(self, key: str) -> Notice | None:
        live = self._live.get(key)
        return None if live is None else live[0]

    def live(self, workspace: WorkspaceId | None = None) -> tuple[Notice, ...]:
        """Live notices (of ``workspace``), highest severity first, then newest first."""
        entries = [
            entry
            for entry in self._live.values()
            if workspace is None or entry[0].workspace is workspace
        ]
        entries.sort(key=lambda entry: (entry[0].severity, entry[1], entry[2]), reverse=True)
        return tuple(entry[0] for entry in entries)

    def top(self, workspace: WorkspaceId) -> Notice | None:
        notices = self.live(workspace)
        return notices[0] if notices else None

    def count(self, workspace: WorkspaceId) -> int:
        return len(self.live(workspace))

    def history(self) -> tuple[Notice, ...]:
        return tuple(self._history)

    def subscribe(self, listener: Listener) -> None:
        self._listeners.append(listener)

    def _notify(self, change: str, notice: Notice) -> None:
        for listener in tuple(self._listeners):
            listener(change, notice)
