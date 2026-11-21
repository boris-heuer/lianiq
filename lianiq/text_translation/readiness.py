"""Translate and Play readiness of the Text translation page (contract.md §5).

Only the directed translation edge and, for Play, the target voice and the Conversation
output device are checked. Recognition, the microphone and the Conversation voice switch are
never read. ``packs`` is any object with ``for_requirement`` (CAP-0171 ``PackCatalog``), so
this module does not import ``lianiq.packs``.
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

TEXT_MODE: Final = UsageMode(InputKind.TYPED, RoutingKind.FIXED, OutputKind.TEXT)  # row 1
SPOKEN_TEXT_MODE: Final = UsageMode(InputKind.TYPED, RoutingKind.FIXED, OutputKind.SPOKEN)  # row 2


class PackLookup(Protocol):
    """The part of the CAP-0171 ``PackCatalog`` used here."""

    def for_requirement(self, requirement: Requirement) -> object | None: ...


class Speakers(Protocol):
    """The part of ``ResolvedDevice`` (Conversation output) used here."""

    @property
    def ready(self) -> bool: ...


class TranslateBlock(StrEnum):
    NONE = "none"
    UNSUPPORTED = "unsupported"
    PACK_MISSING = "pack_missing"


class PlayBlock(StrEnum):
    NONE = "none"
    VOICE_MISSING = "voice_missing"
    SPEAKERS_MISSING = "speakers_missing"


@dataclass(frozen=True, slots=True)
class TextReadiness:
    translate: TranslateBlock
    play: PlayBlock
    missing: tuple[Requirement, ...]  # CAP-0169 order, rendered with describe()


def text_session(source: LanguageId, target: LanguageId, *, spoken: bool) -> SessionPair:
    mode = SPOKEN_TEXT_MODE if spoken else TEXT_MODE
    return SessionPair(LanguagePair(source, target), mode, fixed_source=source)


def text_readiness(
    source: LanguageId,
    target: LanguageId,
    catalog: CapabilityCatalog,
    packs: PackLookup | None,
    speakers: Speakers,
) -> TextReadiness:
    text = check(text_session(source, target, spoken=False), catalog, DeviceReadiness())
    translate = TranslateBlock.NONE
    for requirement in text.missing:  # only the directed translation edge (row 1)
        edge = DirectedEdge(source, target)
        not_configured = catalog.translation(edge).status is ReadinessStatus.NOT_CONFIGURED
        if not_configured and (packs is None or packs.for_requirement(requirement) is None):
            translate = TranslateBlock.UNSUPPORTED
        else:
            translate = TranslateBlock.PACK_MISSING
    spoken = check(
        text_session(source, target, spoken=True),
        catalog,
        DeviceReadiness(playback=speakers.ready),
    )
    kinds = {requirement.kind for requirement in spoken.missing}
    if RequirementKind.VOICE in kinds:
        play = PlayBlock.VOICE_MISSING
    elif RequirementKind.PLAYBACK in kinds:
        play = PlayBlock.SPEAKERS_MISSING
    else:
        play = PlayBlock.NONE
    return TextReadiness(translate, play, spoken.missing)
