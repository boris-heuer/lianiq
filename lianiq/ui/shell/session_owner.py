"""The active-session owner (CAP-0168 contract.md §2, ``lianiq.shell.active-session.v1``).

Qt-free: one session at a time across all modes. A mode asks ``request_start`` before it
opens any stream; while another session is not idle the request raises ``SessionBusy``.
``stop()`` works from every workspace and calls the active mode's registered stopper.
Each start gets a new generation, so a late ``mark_running``/``mark_idle`` of an older
start changes nothing. The conversation mode wraps its ``SessionController`` gate: the
owner records which mode holds the session, the controller keeps the bound pair. A mode
whose stop takes long (the CAP-0177 meeting drains its contributions) registers an
asynchronous stopper: the session then stays *stopping* until the mode reports
``mark_idle`` itself, so no other mode can start while it still holds its devices.

session-status-truthfulness §3.2 (additive): ``stop()`` is a no-op while *stopping*; a
stopper that raises ends the session and tells the ``on_stop_failed`` listeners the mode; a
mode whose stop timed out registers a ``linger`` probe, and every ``request_start`` raises
``SessionStillFinishing`` while that probe reports its worker alive (checked lazily, no
timer).

All calls happen on the GUI thread; worker threads hand results over through ``UiBridge``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from enum import StrEnum

from lianiq.ui.shell.workspaces import WorkspaceId, label, session_busy_message
from lianiq.ui.strings_session import SESSION_STILL_FINISHING

LOGGER = logging.getLogger(__name__)

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


class SessionStillFinishing(SessionBusy):
    """A start was requested while the timed-out stop of ``active`` still has a live worker."""

    def __init__(self, active: WorkspaceId) -> None:
        Exception.__init__(self, SESSION_STILL_FINISHING.format(mode=label(active)))
        self.active = active


class ActiveSessionOwner:
    def __init__(self) -> None:
        self.active: WorkspaceId | None = None
        self.state = SessionState.IDLE
        self.generation = 0
        self._stoppers: dict[WorkspaceId, Callable[[], None]] = {}
        self._asynchronous: set[WorkspaceId] = set()
        self._listeners: list[Listener] = []
        self._stop_failed: list[Callable[[WorkspaceId], None]] = []
        self._lingering: dict[WorkspaceId, Callable[[], bool]] = {}

    def register(
        self, mode: WorkspaceId, stopper: Callable[[], None], *, asynchronous: bool = False
    ) -> None:
        """``stopper`` stops ``mode``'s session and reports ``mark_idle``.

        A synchronous stopper (the default) has stopped when it returns; an asynchronous one
        only begins the stop and must call ``mark_idle`` when the session has ended.
        """
        self._stoppers[mode] = stopper
        if asynchronous:
            self._asynchronous.add(mode)
        else:
            self._asynchronous.discard(mode)

    def request_start(self, mode: WorkspaceId) -> int:
        """Record ``mode`` as starting and return its new generation, or raise ``SessionBusy``."""
        if self.state is not SessionState.IDLE:
            raise SessionBusy(self.active if self.active is not None else mode)
        lingering = self.lingering()
        if lingering is not None:
            raise SessionStillFinishing(lingering)
        self.generation += 1
        self.active = mode
        self._set(SessionState.STARTING)
        return self.generation

    def mark_running(self, generation: int) -> None:
        """The start of ``generation`` opened its streams; ignored for a stale generation."""
        if generation == self.generation and self.state is SessionState.STARTING:
            self._set(SessionState.RUNNING)

    def stop(self) -> None:
        """Stop the active session from any workspace; a no-op while idle or stopping."""
        if self.state in (SessionState.IDLE, SessionState.STOPPING) or self.active is None:
            return
        generation, mode = self.generation, self.active
        stopper = self._stoppers.get(mode)
        asynchronous = stopper is not None and mode in self._asynchronous
        self._set(SessionState.STOPPING)
        if stopper is not None:
            try:
                stopper()
            except Exception:
                LOGGER.exception("The %s stopper raised", mode.value)
                self.mark_idle(generation)
                for listener in tuple(self._stop_failed):
                    listener(mode)
                return
        if asynchronous:
            return  # the mode reports ``mark_idle`` once it has stopped
        # Stoppers are synchronous; a stopper that did not report back still ends the session.
        self.mark_idle(generation)

    def mark_idle(self, generation: int) -> None:
        """The session of ``generation`` ended; ignored for a stale generation."""
        if generation != self.generation or self.state is SessionState.IDLE:
            return
        self.active = None
        self._set(SessionState.IDLE)

    def on_stop_failed(self, listener: Callable[[WorkspaceId], None]) -> None:
        """``listener(mode)`` runs after ``mode``'s stopper raised and the owner went idle."""
        self._stop_failed.append(listener)

    def linger(self, mode: WorkspaceId, alive: Callable[[], bool]) -> None:
        """``mode``'s stop timed out: refuse every start while ``alive()`` is true."""
        self._lingering[mode] = alive

    def lingering(self) -> WorkspaceId | None:
        """The mode whose timed-out worker is still alive; dead probes are dropped."""
        for mode, alive in tuple(self._lingering.items()):
            try:
                still = alive()
            except Exception:
                LOGGER.exception("The %s linger probe raised", mode.value)
                still = False
            if still:
                return mode
            del self._lingering[mode]
        return None

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
