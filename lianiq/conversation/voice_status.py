"""Per-language voice status, the spoken plan and the Conversation Start check (CAP-0167 C §4).

Qt-free; re-exported by ``lianiq.conversation.spoken_output``. A language is spoken in
Conversation iff it is an output language of the session, its CAP-0169 voice is ready, its
configured engine has an engine code for it and its switch (``tts.output``) is not off.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from lianiq.languages.capabilities import CapabilityCatalog, ReadinessStatus
from lianiq.languages.modes import OutputKind, RoutingKind, SessionPair
from lianiq.languages.registry import LanguageId, LanguageRegistry
from lianiq.languages.requirements import (
    DeviceReadiness,
    ModeAvailability,
    Requirement,
    RequirementKind,
    check,
    is_met,
)

if TYPE_CHECKING:
    from lianiq.config import AppConfig
    from lianiq.packs.catalog import PackCatalog

DEFAULT_ENGINE = "piper"
SHERPA_ENGINE = "sherpa-onnx"
# C §9 ``VOICE_NAME_SPEAKER``; the speaker number is shown 1-based.
VOICE_NAME_SPEAKER = "{voice} · speaker {number}"


class VoiceState(StrEnum):
    READY = "ready"
    MISSING = "missing"
    INVALID = "invalid"
    NOT_OUTPUT = "not_output"


@dataclass(frozen=True, slots=True)
class VoiceStatus:
    language: LanguageId
    state: VoiceState
    voice_name: str | None  # None unless READY


def output_languages(session: SessionPair) -> frozenset[LanguageId]:
    """Both pair members, or the fixed target of a fixed direction."""
    if session.mode.routing is RoutingKind.FIXED:
        target = session.fixed_target
        assert target is not None  # SessionPair rejects fixed routing without a source
        return frozenset((target,))
    return frozenset(session.pair.members)


def _engine(config: AppConfig, language: LanguageId):
    return config.tts.engines.get(language)


def voice_status(
    language: LanguageId,
    *,
    catalog: CapabilityCatalog,
    config: AppConfig,
    registry: LanguageRegistry,
    outputs: frozenset[LanguageId],
    packs: PackCatalog | None = None,
) -> VoiceStatus:
    language = registry.get(language).id
    if language not in outputs:
        return VoiceStatus(language, VoiceState.NOT_OUTPUT, None)
    status = catalog.voice(language).status
    engine = _engine(config, language)
    engine_name = DEFAULT_ENGINE if engine is None else engine.engine
    if status.is_ready and engine_name in registry.get(language).engine_codes:
        return VoiceStatus(language, VoiceState.READY, _voice_name(language, config, packs))
    if status is ReadinessStatus.INVALID:
        return VoiceStatus(language, VoiceState.INVALID, None)
    return VoiceStatus(language, VoiceState.MISSING, None)


def _voice_name(language: LanguageId, config: AppConfig, packs: PackCatalog | None) -> str:
    configured = config.tts.voices.get(language, "")
    name = Path(configured).stem
    if packs is not None:
        model = _pack_model(configured, packs)
        name = model if model is not None else name
    speaker = _speaker(language, config)
    return name if speaker is None else VOICE_NAME_SPEAKER.format(voice=name, number=speaker + 1)


def _pack_model(configured: str, packs: PackCatalog) -> str | None:
    """The ``model`` of the voice pack whose ``root`` contains the configured voice."""
    from lianiq.config import PROJECT_ROOT
    from lianiq.packs.catalog import PackKind

    path = Path(configured)
    if path.is_absolute():
        try:
            path = path.relative_to(PROJECT_ROOT)
        except ValueError:
            return None
    voice = PurePosixPath(path.as_posix())
    for pack in packs.packs():
        root = PurePosixPath(pack.root)
        if pack.kind is PackKind.VOICE and (voice == root or root in voice.parents):
            return pack.model
    return None


def _speaker(language: LanguageId, config: AppConfig) -> int | None:
    preference = config.tts.output.get(language)
    if preference is not None and preference.speaker is not None:
        return preference.speaker
    engine = _engine(config, language)
    if engine is not None and engine.engine == SHERPA_ENGINE:
        return engine.speaker_id
    return None


def spoken_plan(statuses: Iterable[VoiceStatus], config: AppConfig) -> frozenset[LanguageId]:
    """The ready languages whose switch is not off (``enabled: None`` counts as on)."""
    plan = set()
    for status in statuses:
        preference = config.tts.output.get(status.language)
        switched_off = preference is not None and preference.enabled is False
        if status.state is VoiceState.READY and not switched_off:
            plan.add(status.language)
    return frozenset(plan)


def conversation_output(outputs: frozenset[LanguageId], plan: frozenset[LanguageId]) -> OutputKind:
    """``SPOKEN`` iff every output language is in the plan (CAP-0169 row 4 or 6)."""
    return OutputKind.SPOKEN if outputs and plan == outputs else OutputKind.TEXT


def spoken_requirements(
    plan: frozenset[LanguageId], registry: LanguageRegistry | None = None
) -> tuple[Requirement, ...]:
    """One voice per plan language in registry order, then playback for a non-empty plan."""
    if registry is None:
        from lianiq.languages.registry import BUILTIN_REGISTRY

        registry = BUILTIN_REGISTRY
    ordered = [item.id for item in registry.languages() if item.id in plan]
    voices = tuple(Requirement(RequirementKind.VOICE, language) for language in ordered)
    return (*voices, Requirement(RequirementKind.PLAYBACK)) if plan else ()


def spoken_session(session: SessionPair, plan: frozenset[LanguageId]) -> SessionPair:
    """``session`` with the output ``conversation_output`` gives for ``plan``."""
    output = conversation_output(output_languages(session), plan)
    return replace(session, mode=replace(session.mode, output=output))


def start_check(
    session: SessionPair,
    plan: frozenset[LanguageId],
    catalog: CapabilityCatalog,
    devices: DeviceReadiness,
) -> ModeAvailability:
    """CAP-0169 ``check`` of the plan's output plus every unmet spoken requirement."""
    availability = check(spoken_session(session, plan), catalog, devices)
    missing = list(availability.missing)
    for requirement in spoken_requirements(plan, catalog.registry):
        if requirement not in missing and not is_met(requirement, catalog, devices):
            missing.append(requirement)
    return ModeAvailability(available=not missing, missing=tuple(missing))
