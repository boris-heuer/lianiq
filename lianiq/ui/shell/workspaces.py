"""The workspace registry (CAP-0168 contract.md §1, ``lianiq.shell.workspace-registry.v1``).

Qt-free: six workspaces in the fixed spec §2.3.1 order with Settings last. A workspace is
enabled, planned (listed, disabled, no page) or experimental (enabled, marked).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from lianiq.ui import strings


class WorkspaceId(StrEnum):
    CONVERSATION = "conversation"
    TEXT_TRANSLATION = "text-translation"
    LISTEN = "listen-and-translate"
    CALL_BRIDGE = "call-bridge"
    LANGUAGE_PACKS = "language-packs"
    SETTINGS = "settings"


class EntryState(StrEnum):
    ENABLED = "enabled"
    PLANNED = "planned"
    EXPERIMENTAL = "experimental"


@dataclass(frozen=True)
class WorkspaceEntry:
    id: WorkspaceId
    label: str  # strings.NAV_*
    state: EntryState

    @property
    def selectable(self) -> bool:
        """Whether the entry has a page: planned entries never change the page."""
        return self.state is not EntryState.PLANNED


DEFAULT_ENTRIES: tuple[WorkspaceEntry, ...] = (
    WorkspaceEntry(WorkspaceId.CONVERSATION, strings.NAV_CONVERSATION, EntryState.ENABLED),
    WorkspaceEntry(WorkspaceId.TEXT_TRANSLATION, strings.NAV_TEXT_TRANSLATION, EntryState.PLANNED),
    WorkspaceEntry(WorkspaceId.LISTEN, strings.NAV_LISTEN, EntryState.PLANNED),
    WorkspaceEntry(WorkspaceId.CALL_BRIDGE, strings.NAV_CALL_BRIDGE, EntryState.EXPERIMENTAL),
    WorkspaceEntry(WorkspaceId.LANGUAGE_PACKS, strings.NAV_LANGUAGE_PACKS, EntryState.PLANNED),
    WorkspaceEntry(WorkspaceId.SETTINGS, strings.NAV_SETTINGS, EntryState.ENABLED),
)


def entry(workspace: WorkspaceId, entries: tuple[WorkspaceEntry, ...] = DEFAULT_ENTRIES):
    """The registry entry of ``workspace``."""
    return next(item for item in entries if item.id is workspace)


def label(workspace: WorkspaceId) -> str:
    """The visible label of ``workspace``, also the ``{mode}`` of the session strings."""
    return entry(workspace).label


def session_busy_message(active: WorkspaceId) -> str:
    """``SESSION_BUSY`` for the mode that owns the running session."""
    return strings.SESSION_BUSY.format(mode=label(active))
