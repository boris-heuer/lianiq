"""Conversation device selection by endpoint identity (CAP-0168 contract §4, §7).

Qt-free. A ``DeviceChoice`` (policy, endpoint ID, last display name) is resolved against
the current inventory; a missing explicit choice stays unavailable and is never replaced
by another device. Labels, reasons and change summaries never contain an endpoint ID.
The inventory itself is read by ``device_inventory`` (re-exported here).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from lianiq.audio.device_inventory import (  # noqa: F401 - re-exported (contract §4)
    ConversationEndpoint,
    ConversationInventory,
    UnusableEndpoint,
    list_conversation_endpoints,
    read_inventory,
    read_native_ids,
    reinitialize_portaudio,
)
from lianiq.audio.endpoints import _names_match, _normalize_name
from lianiq.call_bridge.contracts import AudioEndpointRef, EndpointFlow
from lianiq.ui import strings


class DevicePolicy(StrEnum):
    EXPLICIT = "explicit"
    FOLLOW_DEFAULT = "follow_default"


@dataclass(frozen=True)
class DeviceChoice:
    policy: DevicePolicy
    endpoint_id: str | None = None
    display_name: str | None = None


FOLLOW_DEFAULT = DeviceChoice(DevicePolicy.FOLLOW_DEFAULT)


@dataclass(frozen=True)
class ResolvedDevice:
    choice: DeviceChoice
    endpoint: AudioEndpointRef | None  # None when unavailable or unusable
    available: bool
    usable: bool  # False: absent, or present but its channels cannot serve the flow
    reason: str | None  # user-facing, never an endpoint ID
    label: str  # never contains an endpoint ID

    @property
    def ready(self) -> bool:
        return self.endpoint is not None


def unusable_reason(flow: EndpointFlow) -> str:
    return strings.DEVICE_NO_INPUT if flow is EndpointFlow.CAPTURE else strings.DEVICE_NO_OUTPUT


def display_labels(endpoints: Sequence[ConversationEndpoint]) -> dict[str, str]:
    """Endpoint ID -> label; per flow, repeated names get " (2)", " (3)" in order."""
    labels: dict[str, str] = {}
    seen: dict[tuple[EndpointFlow, str], int] = {}
    for endpoint in endpoints:
        key = (endpoint.flow, endpoint.display_name)
        seen[key] = seen.get(key, 0) + 1
        suffix = "" if seen[key] == 1 else f" ({seen[key]})"
        labels[endpoint.endpoint_id] = f"{endpoint.display_name}{suffix}"
    return labels


def describe(endpoint: ConversationEndpoint) -> str:
    """Tooltip and accessible description: full name, host API and channels; no ID."""
    return strings.DEVICE_DETAILS.format(
        name=endpoint.display_name, host_api=endpoint.host_api, channels=endpoint.channels
    )


def resolve_choice(
    choice: DeviceChoice,
    inventory: Sequence[ConversationEndpoint],
    flow: EndpointFlow,
    default: ConversationEndpoint | None,
) -> ResolvedDevice:
    labels = display_labels(inventory)
    if choice.policy is DevicePolicy.FOLLOW_DEFAULT:
        target = default if default is not None and default.flow is flow else None
        name = labels.get(target.endpoint_id, target.display_name) if target else None
        label = strings.DEVICE_FOLLOW_DEFAULT.format(name=name or strings.DEVICE_NO_DEFAULT)
        return _resolved(choice, target, flow, label)
    target = next(
        (e for e in inventory if e.endpoint_id == choice.endpoint_id and e.flow is flow), None
    )
    if target is None:
        name = choice.display_name or strings.DEVICE_SAVED
        return ResolvedDevice(
            choice, None, False, False, None, strings.DEVICE_UNAVAILABLE.format(name=name)
        )
    return _resolved(choice, target, flow, labels[target.endpoint_id])


def _resolved(choice, target, flow, label) -> ResolvedDevice:
    if target is None:
        return ResolvedDevice(choice, None, False, False, None, label)
    if isinstance(target, UnusableEndpoint):
        reason = unusable_reason(flow)
        if choice.policy is DevicePolicy.EXPLICIT:
            label = strings.DEVICE_UNUSABLE.format(name=label, reason=reason)
        return ResolvedDevice(choice, None, True, False, reason, label)
    return ResolvedDevice(choice, target, True, True, None, label)


# Settings (contract §7) ----------------------------------------------------------------------


def _prefix(flow: EndpointFlow) -> str:
    return "input" if flow is EndpointFlow.CAPTURE else "output"


def is_legacy(audio, flow: EndpointFlow) -> bool:
    """Policy ``null`` and a legacy index set: the choice is migrated (precedence step 3)."""
    prefix = _prefix(flow)
    return getattr(audio, f"{prefix}_policy") is None and (
        getattr(audio, f"{prefix}_device") is not None
    )


def choice_from_settings(
    audio,
    flow: EndpointFlow,
    legacy_names: Mapping[int, str],
    inventory: Sequence[ConversationEndpoint],
) -> DeviceChoice:
    prefix = _prefix(flow)
    policy = getattr(audio, f"{prefix}_policy")
    if policy is not None:
        return DeviceChoice(
            DevicePolicy(policy),
            getattr(audio, f"{prefix}_endpoint_id"),
            getattr(audio, f"{prefix}_device_name"),
        )
    index = getattr(audio, f"{prefix}_device")
    if index is None:
        return FOLLOW_DEFAULT
    name = legacy_names.get(index)
    if name is None:
        return DeviceChoice(DevicePolicy.EXPLICIT, None, strings.DEVICE_SAVED)
    wanted = _normalize_name(name)
    matches = [
        e
        for e in inventory
        if e.flow is flow and _names_match(wanted, _normalize_name(e.display_name))
    ]
    if len(matches) == 1:
        return DeviceChoice(DevicePolicy.EXPLICIT, matches[0].endpoint_id, matches[0].display_name)
    return DeviceChoice(DevicePolicy.EXPLICIT, None, name)


def store_choice(audio, flow: EndpointFlow, choice: DeviceChoice) -> None:
    """Write the three keys of ``flow``; the shell never writes a device index again."""
    prefix = _prefix(flow)
    setattr(audio, f"{prefix}_policy", choice.policy.value)
    setattr(audio, f"{prefix}_endpoint_id", choice.endpoint_id)
    setattr(audio, f"{prefix}_device_name", choice.display_name)
    setattr(audio, f"{prefix}_device", None)


# Inventory changes ---------------------------------------------------------------------------


@dataclass(frozen=True)
class InventoryChange:
    added: tuple[str, ...] = ()  # display labels, never endpoint IDs
    removed: tuple[str, ...] = ()
    reordered: bool = False  # same identities, different enumeration order
    default_changed: bool = False  # the default endpoint identity changed (per flow)

    def is_empty(self) -> bool:
        return not (self.added or self.removed or self.reordered or self.default_changed)

    def summary(self) -> str:
        parts = [strings.DEVICE_ADDED.format(name=name) for name in self.added]
        parts += [strings.DEVICE_REMOVED.format(name=name) for name in self.removed]
        if self.reordered:
            parts.append(strings.DEVICE_REORDERED)
        if self.default_changed:
            parts.append(strings.DEVICE_DEFAULT_MOVED)
        return ", ".join(parts)


def diff_inventory(
    before: Sequence[ConversationEndpoint],
    after: Sequence[ConversationEndpoint],
    default_before: str | None = None,
    default_after: str | None = None,
) -> InventoryChange:
    before_ids = [e.endpoint_id for e in before]
    after_ids = [e.endpoint_id for e in after]
    old_labels, new_labels = display_labels(before), display_labels(after)
    common_before = [i for i in before_ids if i in set(after_ids)]
    common_after = [i for i in after_ids if i in set(before_ids)]
    return InventoryChange(
        added=tuple(new_labels[i] for i in after_ids if i not in set(before_ids)),
        removed=tuple(old_labels[i] for i in before_ids if i not in set(after_ids)),
        reordered=common_before != common_after,
        default_changed=default_before != default_after,
    )


def diff_native(
    inventory: Sequence[ConversationEndpoint],
    known: Mapping[str, str],
    current: Mapping[str, str],
) -> InventoryChange:
    """The identity-only change (ID -> name maps) seen while a stream is open."""
    labels = display_labels(inventory)
    gone = known.keys() - current.keys()
    return InventoryChange(
        added=tuple(name for key, name in current.items() if key not in known),
        removed=tuple(labels.get(key, known[key]) for key in known if key in gone),
    )
