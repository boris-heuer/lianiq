from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType


class EndpointFlow(str, Enum):
    CAPTURE = "capture"
    RENDER = "render"


class EndpointRole(str, Enum):
    LOCAL_MICROPHONE = "local_microphone"
    CALL_MICROPHONE_RENDER = "call_microphone_render"
    CALL_SPEAKER_CAPTURE = "call_speaker_capture"
    LOCAL_HEADPHONES = "local_headphones"


class LaneId(str, Enum):
    OUTBOUND = "outbound"
    INBOUND = "inbound"


class BridgeState(str, Enum):
    STOPPED = "stopped"
    VALIDATING_ENDPOINTS = "validating_endpoints"
    RUNNING = "running"
    DEGRADED = "degraded"
    STOPPING = "stopping"


class BridgeEventKind(str, Enum):
    STATE = "state"
    DROPPED = "dropped"
    ERROR = "error"
    ENDPOINT = "endpoint"


@dataclass(frozen=True, slots=True)
class AudioEndpointRef:
    endpoint_id: str
    display_name: str
    flow: EndpointFlow
    host_api: str
    runtime_index: int
    channels: int = 1
    sample_rate: int = 48_000

    def __post_init__(self) -> None:
        if not self.endpoint_id.strip():
            raise ValueError("endpoint_id must not be empty")
        if self.runtime_index < 0:
            raise ValueError("runtime_index must not be negative")
        if self.channels <= 0 or self.sample_rate <= 0:
            raise ValueError("endpoint channels and sample rate must be positive")


@dataclass(frozen=True, slots=True)
class BridgeEvent:
    lane_id: LaneId | None
    kind: BridgeEventKind
    category: str
    message: str
    sequence: int | None = None


EXPECTED_ENDPOINT_FLOWS = MappingProxyType(
    {
        EndpointRole.LOCAL_MICROPHONE: EndpointFlow.CAPTURE,
        EndpointRole.CALL_MICROPHONE_RENDER: EndpointFlow.RENDER,
        EndpointRole.CALL_SPEAKER_CAPTURE: EndpointFlow.CAPTURE,
        EndpointRole.LOCAL_HEADPHONES: EndpointFlow.RENDER,
    }
)


def validate_endpoint_assignments(
    assignments: Mapping[EndpointRole, AudioEndpointRef],
) -> None:
    missing = [role.value for role in EndpointRole if role not in assignments]
    if missing:
        raise ValueError(f"Missing call bridge endpoint roles: {', '.join(missing)}")

    endpoint_ids: set[str] = set()
    for role, expected_flow in EXPECTED_ENDPOINT_FLOWS.items():
        endpoint = assignments[role]
        if endpoint.flow is not expected_flow:
            raise ValueError(f"{role.value} requires a {expected_flow.value} endpoint")
        if endpoint.endpoint_id in endpoint_ids:
            raise ValueError(f"Endpoint {endpoint.display_name!r} is assigned more than once")
        endpoint_ids.add(endpoint.endpoint_id)
