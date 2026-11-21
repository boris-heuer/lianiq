"""Listen session and Start readiness (CAP-0170 contract.md §2).

Only CAP-0169 requirement row 3 is checked: the source recogniser, the directed
translation edge and the microphone. Voices, playback, the target recogniser and the
reverse edge are never read. ``packs`` is any object with ``for_requirement`` (CAP-0171
``PackCatalog``), so this module does not import ``lianiq.packs``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Final, Protocol

from lianiq.languages.capabilities import DirectedEdge, ReadinessStatus
from lianiq.languages.modes import InputKind, OutputKind, RoutingKind, SessionPair, UsageMode
from lianiq.languages.registry import LanguageId, LanguagePair
from lianiq.languages.requirements import DeviceReadiness, Requirement, RequirementKind, check

if TYPE_CHECKING:
    from lianiq.languages.capabilities import CapabilityCatalog
    from lianiq.ui.shell.workspaces import WorkspaceId

LISTEN_MODE: Final = UsageMode(InputKind.MICROPHONE, RoutingKind.FIXED, OutputKind.TEXT)  # row 3


class PackLookup(Protocol):
    """The part of the CAP-0171 ``PackCatalog`` used here."""

    def for_requirement(self, requirement: Requirement) -> object | None: ...


class Microphone(Protocol):
    """The part of ``ResolvedDevice`` used here."""

    @property
    def ready(self) -> bool: ...


class StartBlock(StrEnum):
    NONE = "none"
    UNSUPPORTED = "unsupported"
    PACK_MISSING = "pack_missing"
    MICROPHONE_MISSING = "microphone_missing"
    BUSY = "busy"


@dataclass(frozen=True, slots=True)
class ListenReadiness:
    block: StartBlock
    missing: tuple[Requirement, ...]  # CAP-0169 row-3 order, rendered with describe()


def listen_session(pair: LanguagePair, source: LanguageId) -> SessionPair:
    return SessionPair(pair, LISTEN_MODE, fixed_source=source)


def _not_configured(requirement: Requirement, catalog: CapabilityCatalog) -> bool:
    subject = str(requirement.subject)
    if requirement.kind is RequirementKind.RECOGNITION:
        status = catalog.recognition(LanguageId(subject)).status
    else:
        status = catalog.translation(DirectedEdge.from_key(subject)).status
    return status is ReadinessStatus.NOT_CONFIGURED


def listen_readiness(
    session: SessionPair,
    catalog: CapabilityCatalog,
    packs: PackLookup | None,
    microphone: Microphone,
    busy: WorkspaceId | None,
) -> ListenReadiness:
    missing = check(session, catalog, DeviceReadiness(microphone=microphone.ready)).missing
    models = [item for item in missing if item.kind is not RequirementKind.MICROPHONE]
    if any(
        _not_configured(item, catalog) and (packs is None or packs.for_requirement(item) is None)
        for item in models
    ):
        block = StartBlock.UNSUPPORTED
    elif models:
        block = StartBlock.PACK_MISSING
    elif missing:
        block = StartBlock.MICROPHONE_MISSING
    elif busy is not None:
        block = StartBlock.BUSY
    else:
        block = StartBlock.NONE
    return ListenReadiness(block, missing)
