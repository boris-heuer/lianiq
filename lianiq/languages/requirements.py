"""Usage mode requirements and their availability check (contract.md §3.1.4).

Requirement table (IS §7; rows 4 and 6 are compositions of confirmed rows):

| # | Mode (input / routing / output) | Required |
|---|---|---|
| 1 | typed / fixed / text | MT ``s>t`` |
| 2 | typed / fixed / spoken | MT ``s>t``, voice ``t``, playback |
| 3 | microphone / fixed / text | STT ``s``, MT ``s>t``, microphone |
| 4 | microphone / fixed / spoken | row 3 + voice ``t``, playback |
| 5 | microphone / bidirectional / text | STT ``a``, ``b``, MT ``a>b``, ``b>a``, microphone |
| 6 | microphone / bidirectional / spoken | row 5 + voice ``a``, ``b``, playback |
| 7 | Call Bridge | STT ``a``, ``b``; MT ``a>b``, ``b>a``; voice ``a``, ``b``; call endpoints |

Typed / bidirectional is rejected by ``SessionPair`` with ``UnsupportedModeError``. Voice
readiness never makes rows 1, 3 or 5 unavailable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from lianiq.languages.capabilities import CapabilityCatalog, DirectedEdge
from lianiq.languages.errors import UnsupportedModeError
from lianiq.languages.modes import InputKind, OutputKind, RoutingKind, SessionPair
from lianiq.languages.registry import LanguageId, LanguageRegistry

# The four explicit Call Bridge endpoints (``call_bridge`` settings, without ``_endpoint_id``).
CALL_ENDPOINT_ROLES: tuple[str, ...] = (
    "local_microphone",
    "call_microphone_render",
    "call_speaker_capture",
    "local_headphones",
)

# English defaults of the missing-requirement texts (contract.md §2.4).
MISSING_RECOGNITION = "speech recognition {language}"
MISSING_TRANSLATION = "translation {source} → {target}"
MISSING_VOICE = "voice {language}"
MISSING_DEVICE = "{device}"
_DEVICE_LABELS = {
    "microphone": "microphone",
    "playback": "playback device",
    "local_microphone": "local microphone endpoint",
    "call_microphone_render": "call microphone endpoint",
    "call_speaker_capture": "call speaker endpoint",
    "local_headphones": "local headphones endpoint",
}


class RequirementKind(str, Enum):
    RECOGNITION = "recognition"
    TRANSLATION = "translation"
    VOICE = "voice"
    MICROPHONE = "microphone"
    PLAYBACK = "playback"
    CALL_ENDPOINTS = "call_endpoints"


@dataclass(frozen=True, slots=True)
class Requirement:
    kind: RequirementKind
    subject: str | None = None  # language ID, edge key, call endpoint role or None

    def __str__(self) -> str:
        return self.kind.value if self.subject is None else f"{self.kind.value} {self.subject}"


@dataclass(frozen=True, slots=True)
class DeviceReadiness:
    """Which non-model resources are currently available for a session."""

    microphone: bool = False
    playback: bool = False
    call_endpoints: frozenset[str] = field(default_factory=frozenset)  # assigned roles


@dataclass(frozen=True, slots=True)
class ModeAvailability:
    available: bool
    missing: tuple[Requirement, ...]  # ordered, rendered by the UI


def _recognition(language: LanguageId) -> Requirement:
    return Requirement(RequirementKind.RECOGNITION, language)


def _translation(source: LanguageId, target: LanguageId) -> Requirement:
    return Requirement(RequirementKind.TRANSLATION, DirectedEdge(source, target).key)


def _voice(language: LanguageId) -> Requirement:
    return Requirement(RequirementKind.VOICE, language)


def ordered_requirements(session: SessionPair) -> tuple[Requirement, ...]:
    """The requirements of ``session`` in display order (models first, then devices)."""
    mode = session.mode
    if mode.input is InputKind.TYPED and mode.routing is RoutingKind.BIDIRECTIONAL:
        raise UnsupportedModeError("Typed input cannot use bidirectional routing")
    a, b = session.pair.members
    result: list[Requirement] = []
    if mode.routing is RoutingKind.FIXED:
        source = session.fixed_source
        if source is None:
            raise UnsupportedModeError("Fixed routing requires a fixed source language")
        target = session.pair.other(source)
        if mode.input is InputKind.MICROPHONE:
            result.append(_recognition(source))
        result.append(_translation(source, target))
        if mode.output is OutputKind.SPOKEN:
            result.append(_voice(target))
    else:
        result += [_recognition(a), _recognition(b), _translation(a, b), _translation(b, a)]
        if mode.output is OutputKind.SPOKEN:
            result += [_voice(a), _voice(b)]
    if mode.call_bridge:
        result += [
            Requirement(RequirementKind.CALL_ENDPOINTS, role) for role in CALL_ENDPOINT_ROLES
        ]
        return tuple(result)
    if mode.input is InputKind.MICROPHONE:
        result.append(Requirement(RequirementKind.MICROPHONE))
    if mode.output is OutputKind.SPOKEN:
        result.append(Requirement(RequirementKind.PLAYBACK))
    return tuple(result)


def requirements(session: SessionPair) -> frozenset[Requirement]:
    return frozenset(ordered_requirements(session))


def is_met(requirement: Requirement, catalog: CapabilityCatalog, devices: DeviceReadiness) -> bool:
    kind, subject = requirement.kind, requirement.subject
    if kind is RequirementKind.RECOGNITION:
        return catalog.recognition(LanguageId(str(subject))).status.is_ready
    if kind is RequirementKind.TRANSLATION:
        return catalog.translation(DirectedEdge.from_key(str(subject))).status.is_ready
    if kind is RequirementKind.VOICE:
        return catalog.voice(LanguageId(str(subject))).status.is_ready
    if kind is RequirementKind.MICROPHONE:
        return devices.microphone
    if kind is RequirementKind.PLAYBACK:
        return devices.playback
    return subject in devices.call_endpoints


def check(
    session: SessionPair, catalog: CapabilityCatalog, devices: DeviceReadiness
) -> ModeAvailability:
    """Check only the requirements of ``session``; name every missing one in order."""
    missing = tuple(
        requirement
        for requirement in ordered_requirements(session)
        if not is_met(requirement, catalog, devices)
    )
    return ModeAvailability(available=not missing, missing=missing)


def describe(requirement: Requirement, registry: LanguageRegistry) -> str:
    """English text naming a requirement with registry display names (contract.md §2.4)."""
    kind, subject = requirement.kind, requirement.subject
    if kind is RequirementKind.RECOGNITION:
        return MISSING_RECOGNITION.format(language=registry.display_name(str(subject)))
    if kind is RequirementKind.TRANSLATION:
        edge = DirectedEdge.from_key(str(subject))
        return MISSING_TRANSLATION.format(
            source=registry.display_name(edge.source), target=registry.display_name(edge.target)
        )
    if kind is RequirementKind.VOICE:
        return MISSING_VOICE.format(language=registry.display_name(str(subject)))
    device = kind.value if subject is None else subject
    return MISSING_DEVICE.format(device=_DEVICE_LABELS.get(device, device))
