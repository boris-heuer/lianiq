from __future__ import annotations

import json
from collections.abc import Mapping
from collections.abc import Set as AbstractSet
from dataclasses import asdict, dataclass
from pathlib import Path

from offline_translator.call_bridge.contracts import (
    AudioEndpointRef,
    BridgeState,
    EndpointRole,
)


@dataclass(frozen=True, slots=True)
class LaneHealthSnapshot:
    captured_seconds: float = 0.0
    queue_age_ms: float = 0.0
    dropped_turns: int = 0
    stt_ms: float = 0.0
    translation_ms: float = 0.0
    tts_ms: float = 0.0
    playback_ms: float = 0.0


def sanitized_diagnostic_snapshot(
    assignments: Mapping[EndpointRole, AudioEndpointRef],
    state: BridgeState,
    lost_roles: AbstractSet[EndpointRole] = frozenset(),
    lane_health: Mapping[str, LaneHealthSnapshot] | None = None,
) -> dict[str, object]:
    """Return support evidence without endpoint IDs, names, transcript, or PCM."""
    return {
        "schema_version": 1,
        "state": state.value,
        "failure_policy": "mute",
        "endpoints": {
            role.value: {
                "flow": endpoint.flow.value,
                "host_api": endpoint.host_api,
                "channels": endpoint.channels,
                "sample_rate": endpoint.sample_rate,
                "available": role not in lost_roles,
            }
            for role, endpoint in assignments.items()
        },
        "lanes": {name: asdict(snapshot) for name, snapshot in (lane_health or {}).items()},
    }


def write_sanitized_diagnostic(
    path: Path,
    assignments: Mapping[EndpointRole, AudioEndpointRef],
    state: BridgeState,
    lost_roles: AbstractSet[EndpointRole] = frozenset(),
    lane_health: Mapping[str, LaneHealthSnapshot] | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            sanitized_diagnostic_snapshot(assignments, state, lost_roles, lane_health),
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
