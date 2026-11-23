"""Notices of the Listen & translate workspace (CAP-0170 contract.md §9, spec §2.2.2).

Qt-free like ``notice_catalog``. ``reason`` is always a ``LISTEN_REASON_*`` text, never an
exception message or user text. Both carry the session generation, so a notice of an older
session is dropped. A model-load failure uses the shared ``model_failed``.
"""

from __future__ import annotations

from lianiq.ui import strings
from lianiq.ui.notice_catalog_base import LISTEN_FAILED, LISTEN_OVERLOAD, _notice
from lianiq.ui.notices import Notice, Severity
from lianiq.ui.shell.workspaces import WorkspaceId

LISTEN = WorkspaceId.LISTEN


def segment_failed(reason: str, where: str, generation: int) -> Notice:
    """A segment could not be recognised or translated; listening continues."""
    return _notice(
        LISTEN_FAILED,
        Severity.WARNING,
        strings.LISTEN_FAILED.format(reason=reason),
        strings.DETAIL_ERROR,
        where,
        strings.CONTINUES_RECORDING,
        LISTEN,
        generation=generation,
    )


def overload(where: str, generation: int) -> Notice:
    """The oldest waiting segment was skipped; shown once per session."""
    return _notice(
        LISTEN_OVERLOAD,
        Severity.INFO,
        strings.LISTEN_OVERLOAD,
        strings.DETAIL_OVERFLOW,
        where,
        strings.CONTINUES_RECORDING,
        LISTEN,
        generation=generation,
    )
