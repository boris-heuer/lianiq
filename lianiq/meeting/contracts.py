"""Meeting roles, options and endpoints (CAP-0177 contract.md §1).

Part of ``lianiq.meeting.dual-input.v1``. Qt-free. Four fixed roles: the speakerphone
microphone and speaker at the table, the PO
microphone and an optional output for local-language speech. Conflicts compare the endpoint
IDs of the resolved endpoints, so a *Your microphone* that follows the Windows default and now
resolves to the table microphone is a conflict. ``LOCAL_IS_TABLE`` only matters while local
speech is on; it never blocks **Start meeting**. The table endpoints are always explicit.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from lianiq.audio.endpoints import _normalize_name
from lianiq.call_bridge.contracts import AudioEndpointRef


class MeetingRole(StrEnum):
    TABLE_CAPTURE = "table_capture"  # speakerphone microphone, table language
    TABLE_RENDER = "table_render"  # speakerphone speaker, table-language speech
    USER_CAPTURE = "user_capture"  # PO microphone, local language
    LOCAL_RENDER = "local_render"  # local-language speech for the PO (headset or speaker)


CAPTURE_ROLES = frozenset({MeetingRole.TABLE_CAPTURE, MeetingRole.USER_CAPTURE})
RENDER_ROLES = frozenset({MeetingRole.TABLE_RENDER, MeetingRole.LOCAL_RENDER})


class TableInputDuringOutput(StrEnum):
    MUTE = "mute"  # default: table input muted during table-language output + guard tail
    OPEN = "open"  # table input stays open; relies on the speakerphone's own echo cancellation


class EndpointConflict(StrEnum):
    USER_IS_TABLE = "user_is_table"  # user capture == table capture
    LOCAL_IS_TABLE = "local_is_table"  # local render == table render


@dataclass(frozen=True, slots=True)
class MeetingEndpoints:
    table_capture: AudioEndpointRef
    table_render: AudioEndpointRef
    user_capture: AudioEndpointRef
    local_render: AudioEndpointRef | None = None  # only needed while local speech is on
    local_render_is_headset: bool = False  # fail-safe: unknown counts as speaker


def endpoint_conflicts(endpoints: MeetingEndpoints) -> tuple[EndpointConflict, ...]:
    """The conflicts of the resolved endpoints, in contract order."""
    conflicts: list[EndpointConflict] = []
    if endpoints.user_capture.endpoint_id == endpoints.table_capture.endpoint_id:
        conflicts.append(EndpointConflict.USER_IS_TABLE)
    local = endpoints.local_render
    if local is not None and local.endpoint_id == endpoints.table_render.endpoint_id:
        conflicts.append(EndpointConflict.LOCAL_IS_TABLE)
    return tuple(conflicts)


def suggest_table_partner(
    chosen: AudioEndpointRef, inventory: Sequence[AudioEndpointRef]
) -> AudioEndpointRef | None:
    """The other-flow endpoint of the same device, only if exactly one matches.

    The device name is the text in the last parentheses of the WASAPI name (for example
    ``Speakers (Jabra Speak2 75)``), else the whole name, compared with the CAP-0168 name
    normalisation. Otherwise ``None``: the PO picks the partner, and can always override it.
    """
    wanted = _device_name(chosen.display_name)
    if not wanted:
        return None
    matches = [
        endpoint
        for endpoint in inventory
        if endpoint.flow is not chosen.flow and _device_name(endpoint.display_name) == wanted
    ]
    return matches[0] if len(matches) == 1 else None


def _device_name(display_name: str) -> str:
    name = display_name.rstrip()
    if name.endswith(")"):
        depth = 0
        for index in range(len(name) - 1, -1, -1):
            if name[index] == ")":
                depth += 1
            elif name[index] == "(":
                depth -= 1
                if depth == 0:
                    return _normalize_name(name[index + 1 : -1])
    return _normalize_name(name)
