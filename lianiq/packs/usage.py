"""Usage profiles and the readiness review (CAP-0171 contract.md §7). Qt-free.

The profile table is the baseline ``lianiq.language.usage-readiness.v1``. Requirements come only
from CAP-0169 ``ordered_requirements`` and ``meeting_local_speech_requirements``; a profile
only names the session it builds. The labels are the §11 ``USAGE_*`` strings.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import TYPE_CHECKING

from lianiq.languages.capabilities import CapabilityCatalog, DirectedEdge, ReadinessStatus
from lianiq.languages.modes import (
    CALL_BRIDGE_MODE,
    MEETING_MODE,
    InputKind,
    OutputKind,
    RoutingKind,
    SessionPair,
    UsageMode,
)
from lianiq.languages.registry import BUILTIN_REGISTRY, LanguageId, LanguagePair
from lianiq.languages.requirements import (
    CALL_ENDPOINT_ROLES,
    MEETING_ENDPOINT_ROLES,
    DeviceReadiness,
    Requirement,
    RequirementKind,
    describe,
    is_met,
    meeting_local_speech_requirements,
    ordered_requirements,
)
from lianiq.packs.catalog import PackCatalog, PackDefinition
from lianiq.text_translation.readiness import text_session
from lianiq.ui import strings_packs as labels
from lianiq.ui.shell.workspaces import WorkspaceId

if TYPE_CHECKING:
    from lianiq.config import AppConfig


class UsageAvailability(StrEnum):
    ENABLED = "enabled"
    EXPERIMENTAL = "experimental"
    PLANNED = "planned"


@dataclass(frozen=True, slots=True)
class UsageProfile:
    id: str
    label: str
    workspace: WorkspaceId
    availability: UsageAvailability
    session: Callable[[LanguagePair, AppConfig], SessionPair] | None  # None when planned
    optional: Callable[[SessionPair], tuple[Requirement, ...]] | None
    device_roles: tuple[str, ...]  # rendered role labels for the audio check
    both_directions: bool = False  # also cover the reverse of a fixed-routing session (C §9)

    def _sessions(self, pair: LanguagePair, config: AppConfig) -> tuple[SessionPair, ...]:
        if self.session is None:
            return ()
        session = self.session(pair, config)
        if not self.both_directions:
            return (session,)
        if session.mode.routing is not RoutingKind.FIXED:
            raise ValueError("both_directions needs a fixed-routing session")
        return session, replace(session, fixed_source=session.fixed_target)

    def _union(self, parts: Sequence[tuple[Requirement, ...]]) -> tuple[Requirement, ...]:
        merged = tuple(dict.fromkeys(item for part in parts for item in part))
        if not self.both_directions:
            return merged
        return tuple(sorted(merged, key=lambda item: _KIND_ORDER.index(item.kind)))  # stable

    def required(self, pair: LanguagePair, config: AppConfig) -> tuple[Requirement, ...]:
        """CAP-0169 ``ordered_requirements`` of each covered session, merged; () when planned."""
        return self._union([ordered_requirements(s) for s in self._sessions(pair, config)])

    def optional_requirements(
        self, pair: LanguagePair, config: AppConfig
    ) -> tuple[Requirement, ...]:
        """``self.optional(s)`` of each covered session minus ``required``; () when none."""
        if self.optional is None:
            return ()
        optional = self.optional
        merged = self._union([optional(s) for s in self._sessions(pair, config)])
        required = set(self.required(pair, config))
        return tuple(item for item in merged if item not in required)


_KIND_ORDER = tuple(RequirementKind)  # CAP-0169 display order of the kinds
_TEXT_CONVERSATION = UsageMode(InputKind.MICROPHONE, RoutingKind.BIDIRECTIONAL, OutputKind.TEXT)


def _conversation(pair: LanguagePair, config: AppConfig) -> SessionPair:
    return SessionPair(pair, _TEXT_CONVERSATION)  # CAP-0169 row 5


def _spoken_extras(session: SessionPair) -> tuple[Requirement, ...]:
    """The spoken row minus the text row: row 6 minus 5 (voices, playback), row 2 minus 1."""
    spoken = replace(session, mode=replace(session.mode, output=OutputKind.SPOKEN))
    text = set(ordered_requirements(session))
    return tuple(item for item in ordered_requirements(spoken) if item not in text)


def _text(pair: LanguagePair, config: AppConfig) -> SessionPair:
    return text_session(pair.first, pair.second, spoken=False)  # row 1; reverse via both_directions


def _local(pair: LanguagePair, language: str) -> LanguageId:
    # A stored local language outside the reviewed pair falls back to the first member.
    return LanguageId(language) if language in pair else pair.first


def _call_bridge(pair: LanguagePair, config: AppConfig) -> SessionPair:
    local = _local(pair, config.call_bridge.local_language)
    return SessionPair(pair, CALL_BRIDGE_MODE, local_language=local)  # row 7


def _meeting(pair: LanguagePair, config: AppConfig) -> SessionPair:
    return SessionPair(
        pair, MEETING_MODE, local_language=_local(pair, config.meeting.local_language)
    )


def _role_labels(kind: RequirementKind, roles: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(describe(Requirement(kind, role), BUILTIN_REGISTRY).capitalize() for role in roles)


USAGE_PROFILES: tuple[UsageProfile, ...] = (
    UsageProfile(
        "conversation",
        labels.USAGE_CONVERSATION,
        WorkspaceId.CONVERSATION,
        UsageAvailability.ENABLED,
        _conversation,
        _spoken_extras,
        ("Microphone", "Speakers"),
    ),
    UsageProfile(
        "call-bridge",
        labels.USAGE_CALL_BRIDGE,
        WorkspaceId.CALL_BRIDGE,
        UsageAvailability.EXPERIMENTAL,
        _call_bridge,
        None,
        _role_labels(RequirementKind.CALL_ENDPOINTS, CALL_ENDPOINT_ROLES),
    ),
    UsageProfile(
        "meeting",
        labels.USAGE_MEETING,
        WorkspaceId.MEETING,
        UsageAvailability.ENABLED,
        _meeting,
        meeting_local_speech_requirements,
        _role_labels(RequirementKind.MEETING_ENDPOINTS, MEETING_ENDPOINT_ROLES),
    ),
    UsageProfile(
        "text-translation",
        labels.USAGE_TEXT,
        WorkspaceId.TEXT_TRANSLATION,
        UsageAvailability.ENABLED,
        _text,
        _spoken_extras,
        ("Speakers",),
        both_directions=True,
    ),
    UsageProfile(
        "listen-and-translate",
        labels.USAGE_LISTEN,
        WorkspaceId.LISTEN,
        UsageAvailability.PLANNED,
        None,
        None,
        (),
    ),
)


class ReviewStatus(StrEnum):  # declared from best to worst
    READY = "ready"
    NOT_INSTALLED = "not_installed"
    FILES_MISSING = "files_missing"
    INVALID = "invalid"
    DEVICE_NOT_FOUND = "device_not_found"


_SEVERITY = {status: rank for rank, status in enumerate(ReviewStatus)}


@dataclass(frozen=True, slots=True)
class ReviewRow:
    pack_id: str | None  # None for a device row and for a requirement no catalog pack covers
    requirements: tuple[Requirement, ...]
    status: ReviewStatus  # worst status of its requirements
    optional: bool  # true iff no selected usage requires it
    needed_by: tuple[str, ...]  # labels of the selected usages that require it, profile order


@dataclass(frozen=True, slots=True)
class ReadinessReview:
    rows: tuple[ReviewRow, ...]  # packs in first-requirement order, then devices
    missing_bytes: int  # sum of download_bytes of packs not ready
    free_bytes: int


_DEVICE_KINDS = frozenset(
    {
        RequirementKind.MICROPHONE,
        RequirementKind.PLAYBACK,
        RequirementKind.CALL_ENDPOINTS,
        RequirementKind.MEETING_ENDPOINTS,
    }
)


def is_device_row(row: ReviewRow) -> bool:
    """Device rows are told apart by requirement kind: ``pack_id`` is also None for a
    capability requirement that no catalog pack covers."""
    return row.requirements[0].kind in _DEVICE_KINDS


def _capability_status(requirement: Requirement, catalog: CapabilityCatalog) -> ReadinessStatus:
    subject = str(requirement.subject)
    if requirement.kind is RequirementKind.RECOGNITION:
        return catalog.recognition(LanguageId(subject)).status
    if requirement.kind is RequirementKind.TRANSLATION:
        return catalog.translation(DirectedEdge.from_key(subject)).status
    return catalog.voice(LanguageId(subject)).status


def _status(
    requirement: Requirement,
    pack: PackDefinition | None,
    catalog: CapabilityCatalog,
    devices: DeviceReadiness,
) -> ReviewStatus:
    if requirement.kind in _DEVICE_KINDS:
        met = is_met(requirement, catalog, devices)
        return ReviewStatus.READY if met else ReviewStatus.DEVICE_NOT_FOUND
    status = _capability_status(requirement, catalog)
    if status.is_ready:
        return ReviewStatus.READY
    if status is ReadinessStatus.INVALID:
        return ReviewStatus.INVALID
    if pack is not None and status is ReadinessStatus.MISSING:
        base = catalog.probe.root / pack.root
        if any((base / item.path).is_file() for item in pack.files):
            return ReviewStatus.FILES_MISSING
    return ReviewStatus.NOT_INSTALLED


@dataclass(slots=True)
class _Group:
    pack: PackDefinition | None
    requirements: list[Requirement] = field(default_factory=list)
    needed_by: list[str] = field(default_factory=list)


def _rank(profile: UsageProfile) -> int:
    ids = [item.id for item in USAGE_PROFILES]
    return ids.index(profile.id) if profile.id in ids else len(ids)


def readiness_review(
    usages: Sequence[UsageProfile],
    pair: LanguagePair,
    config: AppConfig,
    catalog: CapabilityCatalog,
    packs: PackCatalog,
    devices: DeviceReadiness,
    free_bytes: int,
) -> ReadinessReview:
    """One row per pack, then one per device role, for the selected usages (AC-05)."""
    groups: dict[object, _Group] = {}
    for profile in sorted(usages, key=_rank):
        required = profile.required(pair, config)
        entries = [(item, True) for item in required]
        entries += [(item, False) for item in profile.optional_requirements(pair, config)]
        for requirement, needed in entries:
            pack = packs.for_requirement(requirement)
            key: object = pack.id if pack is not None else requirement
            group = groups.setdefault(key, _Group(pack))
            if requirement not in group.requirements:
                group.requirements.append(requirement)
            if needed and profile.label not in group.needed_by:
                group.needed_by.append(profile.label)
    rows: list[ReviewRow] = []
    missing = 0
    for group in groups.values():
        statuses = [_status(item, group.pack, catalog, devices) for item in group.requirements]
        status = max(statuses, key=_SEVERITY.__getitem__)
        pack_id = group.pack.id if group.pack is not None else None
        rows.append(
            ReviewRow(
                pack_id, tuple(group.requirements), status, not group.needed_by, (*group.needed_by,)
            )
        )
        if group.pack is not None and status is not ReviewStatus.READY:
            missing += group.pack.download_bytes
    rows.sort(key=lambda row: row.requirements[0].kind in _DEVICE_KINDS)  # stable: packs first
    return ReadinessReview(tuple(rows), missing, free_bytes)
