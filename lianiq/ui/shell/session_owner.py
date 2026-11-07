"""The active-session owner (CAP-0168 contract.md §2, ``lianiq.shell.active-session.v1``).

Qt-free: one session at a time across all modes. A mode asks ``request_start`` before it
opens any stream; while another session is not idle the request raises ``SessionBusy``.
``stop()`` works from every workspace and calls the active mode's registered stopper.
Each start gets a new generation, so a late ``mark_running``/``mark_idle`` of an older
start changes nothing. The conversation mode wraps its ``SessionController`` gate: the
owner records which mode holds the session, the controller keeps the bound pair.

All calls happen on the GUI thread; worker threads hand results over through ``UiBridge``.
"""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum

from lianiq.ui.shell.workspaces import WorkspaceId, session_busy_message

Listener = Callable[["SessionState", WorkspaceId | None], None]


class SessionState(StrEnum):
    IDLE = "idle"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"


class SessionBusy(Exception):
    """A start was requested while another session is not idle."""

    def __init__(self, active: WorkspaceId) -> None:
        super().__init__(session_busy_message(active))
        self.active = active


class ActiveSessionOwner:
    def __init__(self) -> None:
        self.active: WorkspaceId | None = None
        self.state = SessionState.IDLE
        self.generation = 0
        self._stoppers: dict[WorkspaceId, Callable[[], None]] = {}
        self._listeners: list[Listener] = []

    def register(self, mode: WorkspaceId, stopper: Callable[[], None]) -> None:
        """``stopper`` stops ``mode``'s session and reports ``mark_idle`` (synchronously)."""
        self._stoppers[mode] = stopper

    def request_start(self, mode: WorkspaceId) -> int:
        """Record ``mode`` as starting and return its new generation, or raise ``SessionBusy``."""
        if self.state is not SessionState.IDLE:
            raise SessionBusy(self.active if self.active is not None else mode)
        self.generation += 1
        self.active = mode
        self._set(SessionState.STARTING)
        return self.generation

    def mark_running(self, generation: int) -> None:
        """The start of ``generation`` opened its streams; ignored for a stale generation."""
        if generation == self.generation and self.state is SessionState.STARTING:
            self._set(SessionState.RUNNING)

    def stop(self) -> None:
        """Stop the active session from any workspace; a no-op while idle."""
        if self.state is SessionState.IDLE or self.active is None:
            return
        generation = self.generation
        stopper = self._stoppers.get(self.active)
        self._set(SessionState.STOPPING)
        if stopper is not None:
            stopper()
        # Stoppers are synchronous; a stopper that did not report back still ends the session.
        self.mark_idle(generation)

    def mark_idle(self, generation: int) -> None:
        """The session of ``generation`` ended; ignored for a stale generation."""
        if generation != self.generation or self.state is SessionState.IDLE:
            return
        self.active = None
        self._set(SessionState.IDLE)

    def subscribe(self, listener: Listener) -> None:
        """``listener(state, active)`` runs after every state change."""
        self._listeners.append(listener)

    def busy_for(self, mode: WorkspaceId) -> WorkspaceId | None:
        """The other mode whose session blocks a start of ``mode``, or ``None``."""
        if self.state is SessionState.IDLE or self.active is mode:
            return None
        return self.active

    def _set(self, state: SessionState) -> None:
        self.state = state
        for listener in tuple(self._listeners):
            listener(state, self.active)
