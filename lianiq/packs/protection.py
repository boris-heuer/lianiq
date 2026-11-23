"""Packs used by the active session (CAP-0171 contract.md §8). Qt-free.

The code that calls ``ActiveSessionOwner.request_start`` binds the session it started right
after the call returns (Conversation, Call Bridge, Meeting with its local-speech switch);
the tracker clears itself when the owner becomes idle. ``packs_in_use`` maps the bound
session's requirements through the pack catalog; a running session without a bound usage
protects every installed pack (contract.md §8), so a pack that is not installed can still be
installed meanwhile. Any job (install, update, remove) on a protected pack raises
``PackInUse(mode)``; installing a pack outside the set stays allowed.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from lianiq.languages.modes import SessionPair
from lianiq.languages.registry import LanguageId
from lianiq.languages.requirements import (
    Requirement,
    RequirementKind,
    meeting_local_speech_requirements,
    requirements,
)
from lianiq.packs.catalog import PackCatalog, PackDefinition
from lianiq.packs.errors import PackInUse
from lianiq.ui.shell.session_owner import SessionState
from lianiq.ui.shell.workspaces import WorkspaceId, label

if TYPE_CHECKING:
    from lianiq.ui.shell.session_owner import ActiveSessionOwner

# The contract allows only an install of a pack outside the in-use set; an install of a
# used pack ("Download again" over a Failed pack) would swap files the session holds open.
PROTECTED_OPERATIONS = frozenset({"install", "update", "remove"})
# The owner records its mode whenever it is not idle; this label is a defensive fallback.
FALLBACK_MODE = WorkspaceId.CONVERSATION


@dataclass(frozen=True, slots=True)
class ActiveUsage:
    mode: WorkspaceId
    session: SessionPair
    local_speech: bool  # Meeting only: the optional local speech is on
    # The voices the session plans to speak beyond its requirements (CAP-0167): the spoken
    # plan of a Conversation whose plan covers only some output languages, the Call Bridge
    # lane voices bound at Start.
    voices: frozenset[LanguageId] = frozenset()


class ActiveUsageTracker:
    def __init__(self, owner: ActiveSessionOwner) -> None:
        self._current: ActiveUsage | None = None
        owner.subscribe(self._on_state)

    def _on_state(self, state: SessionState, active: WorkspaceId | None) -> None:
        if state is SessionState.IDLE:
            self._current = None

    def bind(self, usage: ActiveUsage) -> None:
        """Called right after ``request_start`` succeeds."""
        self._current = usage

    def set_local_speech(self, on: bool) -> None:
        """The Meeting local-speech switch changed during a session."""
        if self._current is not None:
            self._current = replace(self._current, local_speech=on)

    @property
    def current(self) -> ActiveUsage | None:
        return self._current


def packs_in_use(
    owner: ActiveSessionOwner,
    tracker: ActiveUsageTracker,
    packs: PackCatalog,
    installed: Iterable[str] | None = None,
) -> frozenset[str]:
    """Ids of the packs the active session uses; every installed pack while it is unbound.

    ``installed`` holds the ids of the installed packs; ``None`` (not known) counts every
    catalog pack as installed, so a caller that cannot tell still protects them all.
    """
    if owner.state is SessionState.IDLE:
        return frozenset()
    usage = tracker.current
    if usage is None:
        ids = frozenset(pack.id for pack in packs.packs())
        return ids if installed is None else ids & frozenset(installed)
    needed = set(requirements(usage.session))
    if usage.local_speech and usage.session.mode.meeting:
        needed.update(meeting_local_speech_requirements(usage.session))
    needed.update(Requirement(RequirementKind.VOICE, language) for language in usage.voices)
    found = (packs.for_requirement(requirement) for requirement in needed)
    return frozenset(pack.id for pack in found if pack is not None)


def in_use_guard(
    owner: ActiveSessionOwner,
    tracker: ActiveUsageTracker,
    packs: PackCatalog,
    installed: Callable[[], Iterable[str]] | None = None,
) -> Callable[[PackDefinition, str], None]:
    """The ``PackJobRunner`` guard: refuse every job on a pack the active session uses.

    ``installed`` returns the installed pack ids at the time of each job start.
    """

    def guard(pack: PackDefinition, operation: str) -> None:
        if operation not in PROTECTED_OPERATIONS:
            return
        known = installed() if installed is not None else None
        if pack.id in packs_in_use(owner, tracker, packs, known):
            usage = tracker.current
            mode = usage.mode if usage is not None else owner.active
            raise PackInUse(label(mode if mode is not None else FALLBACK_MODE))

    return guard
