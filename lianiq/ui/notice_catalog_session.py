"""Stop and refused-start notices of every mode (session-status-truthfulness spec §2.2.2).

Qt-free builders, re-exported by ``notice_catalog``:

| Case | Key | Severity |
|---|---|---|
| a stop reached its bound with turns not finished | ``session.stop-timeout`` | info |
| a mode's stopper raised | ``session.stop-failed`` | warning |
| a start while a timed-out worker is still alive | ``session.still-finishing`` | info |
"""

from __future__ import annotations

from lianiq.ui import strings
from lianiq.ui import strings_session as session_strings
from lianiq.ui.notice_catalog_base import _notice, source
from lianiq.ui.notices import Notice, Severity
from lianiq.ui.shell.workspaces import WorkspaceId, label

STOP_TIMEOUT_KEY = "session.stop-timeout"
STOP_FAILED_KEY = "session.stop-failed"
STILL_FINISHING_KEY = "session.still-finishing"


def stop_timeout(mode: WorkspaceId, count: int, generation: int | None = None) -> Notice:
    """``mode`` stopped at its bound; ``count`` turns were not finished (spec §2.2.2)."""
    title = session_strings.counted(
        session_strings.SESSION_STOP_TIMEOUT.replace("{mode}", label(mode)), count
    )
    return _notice(
        STOP_TIMEOUT_KEY,
        Severity.INFO,
        title,
        session_strings.DETAIL_TURNS_DROPPED,
        source(mode),
        strings.CONTINUES_STOPPED,
        mode,
        generation=generation,
    )


def stop_failed(mode: WorkspaceId) -> Notice:
    """``mode``'s stopper raised; the owner is idle again (spec §2.2.2, AC-04)."""
    return _notice(
        STOP_FAILED_KEY,
        Severity.WARNING,
        session_strings.SESSION_STOP_FAILED.format(mode=label(mode)),
        strings.DETAIL_ERROR,
        source(mode),
        strings.CONTINUES_STOPPED,
        mode,
    )


def still_finishing(mode: WorkspaceId, lingering: WorkspaceId) -> Notice:
    """A start of ``mode`` refused while ``lingering``'s timed-out worker lives (AC-05)."""
    return _notice(
        STILL_FINISHING_KEY,
        Severity.INFO,
        session_strings.SESSION_STILL_FINISHING.format(mode=label(lingering)),
        strings.DETAIL_NONE,
        source(mode),
        strings.CONTINUES_NOT_STARTED,
        mode,
    )
