"""Call Bridge Start readiness: every blocking reason, in order (CAP-0166 spec §3.1, AC-02).

``assignments`` maps each ``EndpointRole`` to its persisted endpoint ID or ``None``: a saved
ID may be stale, so it is resolved here against ``inventory`` (``None`` when enumeration
failed, so every assigned ID is *not found*). Unlike the raising
``validate_endpoint_assignments``, which stops at its first problem, each role is checked on
its own against the same ``EXPECTED_ENDPOINT_FLOWS`` table, so every reason is listed.
``availability`` is the ``check_call_bridge`` (row 7) result; its endpoint items are left
out because each role reports its own. Pure and Qt-free.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from lianiq.audio.endpoints import EndpointInventory, _normalize_name
from lianiq.call_bridge import texts
from lianiq.call_bridge.contracts import (
    EXPECTED_ENDPOINT_FLOWS,
    AudioEndpointRef,
    EndpointFlow,
    EndpointRole,
)
from lianiq.languages.errors import UnsupportedModeError
from lianiq.languages.modes import SessionPair
from lianiq.languages.registry import BUILTIN_REGISTRY, LanguageRegistry
from lianiq.languages.requirements import ModeAvailability, RequirementKind, describe
from lianiq.meeting.contracts import suggest_table_partner


class ReadinessCode(StrEnum):
    MISSING_ENDPOINT = "missing_endpoint"
    ENDPOINT_NOT_FOUND = "endpoint_not_found"
    WRONG_FLOW = "wrong_flow"
    DUPLICATE_ENDPOINT = "duplicate_endpoint"
    SAME_CABLE = "same_cable"
    AMBIGUOUS_ENDPOINT = "ambiguous_endpoint"
    MODE_UNAVAILABLE = "mode_unavailable"
    MODELS_WARMING = "models_warming"
    SESSION_BUSY = "session_busy"
    RUNNING = "running"


@dataclass(frozen=True, slots=True)
class BlockingReason:
    code: ReadinessCode
    role: EndpointRole | None
    text: str


def configured_assignments(config: Any) -> dict[EndpointRole, str | None]:
    """The persisted endpoint ID of each role from ``CallBridgeConfig`` (``enabled`` unused)."""
    return {role: getattr(config, f"{role.value}_endpoint_id") for role in EndpointRole}


def evaluate_readiness(
    assignments: Mapping[EndpointRole, str | None],
    inventory: EndpointInventory | None,
    session: SessionPair,
    availability: ModeAvailability,
    *,
    models_ready: bool,
    busy_reason: str | None,
    running: bool,
    registry: LanguageRegistry = BUILTIN_REGISTRY,
) -> tuple[BlockingReason, ...]:
    """Every reason Start is blocked, in path-box order; empty ⇔ Start may be enabled."""
    if not session.mode.call_bridge:
        raise UnsupportedModeError("Call Bridge readiness applies to Call Bridge sessions only")
    endpoints = inventory.endpoints if inventory is not None else ()
    by_id = {endpoint.endpoint_id: endpoint for endpoint in endpoints}
    reasons: list[BlockingReason] = []
    resolved: dict[EndpointRole, AudioEndpointRef] = {}
    for role, flow in EXPECTED_ENDPOINT_FLOWS.items():
        endpoint_id = assignments.get(role)
        endpoint = by_id.get(endpoint_id) if endpoint_id else None
        if not endpoint_id:
            reasons.append(_reason(ReadinessCode.MISSING_ENDPOINT, role, texts.R_SELECT))
        elif endpoint is None:
            reasons.append(_reason(ReadinessCode.ENDPOINT_NOT_FOUND, role, texts.R_NOT_FOUND))
        elif endpoint.flow is not flow:
            text = texts.R_NEEDS_CAPTURE if flow is EndpointFlow.CAPTURE else texts.R_NEEDS_RENDER
            reasons.append(_reason(ReadinessCode.WRONG_FLOW, role, text))
        elif _same_name_count(endpoint, endpoints) > 1:
            reasons.append(_reason(ReadinessCode.AMBIGUOUS_ENDPOINT, role, texts.R_AMBIGUOUS))
        else:
            resolved[role] = endpoint
    roles = list(EXPECTED_ENDPOINT_FLOWS)
    for index, first in enumerate(roles):
        for second in roles[index + 1 :]:
            if assignments.get(first) and assignments.get(first) == assignments.get(second):
                text = texts.R_DUPLICATE.format(
                    role_a=texts.ROLE_LABELS[first], role_b=texts.ROLE_LABELS[second]
                )
                reasons.append(BlockingReason(ReadinessCode.DUPLICATE_ENDPOINT, first, text))
    call_mic = resolved.get(EndpointRole.CALL_MICROPHONE_RENDER)
    call_speaker = resolved.get(EndpointRole.CALL_SPEAKER_CAPTURE)
    # The meeting device-name pairing rule: both sides of one cable share its device name.
    if call_mic and call_speaker and suggest_table_partner(call_mic, (call_speaker,)):
        reasons.append(BlockingReason(ReadinessCode.SAME_CABLE, None, texts.R_SAME_CABLE))
    for requirement in availability.missing:
        if requirement.kind is not RequirementKind.CALL_ENDPOINTS:
            text = texts.R_MODE_UNAVAILABLE.format(item=describe(requirement, registry))
            reasons.append(BlockingReason(ReadinessCode.MODE_UNAVAILABLE, None, text))
    if not models_ready:
        reasons.append(BlockingReason(ReadinessCode.MODELS_WARMING, None, texts.R_MODELS_WARMING))
    if busy_reason:
        reasons.append(BlockingReason(ReadinessCode.SESSION_BUSY, None, busy_reason))
    if running:
        reasons.append(BlockingReason(ReadinessCode.RUNNING, None, texts.R_RUNNING))
    return tuple(reasons)


def _reason(code: ReadinessCode, role: EndpointRole, template: str) -> BlockingReason:
    return BlockingReason(code, role, template.format(role=texts.ROLE_LABELS[role]))


def _same_name_count(endpoint: AudioEndpointRef, endpoints: tuple[AudioEndpointRef, ...]) -> int:
    name = _normalize_name(endpoint.display_name)
    return sum(
        1
        for candidate in endpoints
        if candidate.flow is endpoint.flow and _normalize_name(candidate.display_name) == name
    )
