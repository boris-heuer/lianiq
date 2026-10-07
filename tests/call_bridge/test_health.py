from __future__ import annotations

import json

from lianiq.call_bridge.contracts import (
    AudioEndpointRef,
    BridgeState,
    EndpointFlow,
    EndpointRole,
)
from lianiq.call_bridge.health import write_sanitized_diagnostic


def test_diagnostic_export_contains_capabilities_but_no_endpoint_identifier_or_name(
    tmp_path,
) -> None:
    secret_id = "windows-mmdevice:v1:capture:user-specific-guid"
    secret_name = "User-specific private headset"
    assignments = {
        role: AudioEndpointRef(
            f"{secret_id}-{role.value}",
            f"{secret_name}-{role.value}",
            EndpointFlow.CAPTURE
            if role in {EndpointRole.LOCAL_MICROPHONE, EndpointRole.CALL_SPEAKER_CAPTURE}
            else EndpointFlow.RENDER,
            "Windows WASAPI",
            index,
        )
        for index, role in enumerate(EndpointRole)
    }
    path = tmp_path / "diagnostic.json"

    write_sanitized_diagnostic(path, assignments, BridgeState.DEGRADED)

    content = path.read_text(encoding="utf-8")
    parsed = json.loads(content)
    assert secret_id not in content
    assert secret_name not in content
    assert parsed["endpoints"]["local_microphone"]["host_api"] == "Windows WASAPI"
