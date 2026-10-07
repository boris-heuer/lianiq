from __future__ import annotations

import argparse
from pathlib import Path

from lianiq.audio.endpoints import list_audio_endpoints
from lianiq.call_bridge.contracts import BridgeState, EndpointFlow, EndpointRole
from lianiq.call_bridge.health import write_sanitized_diagnostic
from lianiq.config import AppConfig


def main() -> int:
    parser = argparse.ArgumentParser(description="Export redacted call bridge endpoint diagnostics")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("logs/call-bridge-diagnostic.json"),
    )
    arguments = parser.parse_args()
    config = AppConfig.load()
    inventory = list_audio_endpoints()
    endpoint_ids = {
        EndpointRole.LOCAL_MICROPHONE: config.call_bridge.local_microphone_endpoint_id,
        EndpointRole.CALL_MICROPHONE_RENDER: config.call_bridge.call_microphone_render_endpoint_id,
        EndpointRole.CALL_SPEAKER_CAPTURE: config.call_bridge.call_speaker_capture_endpoint_id,
        EndpointRole.LOCAL_HEADPHONES: config.call_bridge.local_headphones_endpoint_id,
    }
    flows = {
        EndpointRole.LOCAL_MICROPHONE: EndpointFlow.CAPTURE,
        EndpointRole.CALL_MICROPHONE_RENDER: EndpointFlow.RENDER,
        EndpointRole.CALL_SPEAKER_CAPTURE: EndpointFlow.CAPTURE,
        EndpointRole.LOCAL_HEADPHONES: EndpointFlow.RENDER,
    }
    assignments = {}
    for role, endpoint_id in endpoint_ids.items():
        if endpoint_id is None:
            raise SystemExit(f"Call bridge endpoint is not configured: {role.value}")
        assignments[role] = inventory.resolve(endpoint_id, flows[role])
    write_sanitized_diagnostic(arguments.output, assignments, BridgeState.STOPPED)
    print(f"Redacted diagnostics written to {arguments.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
