from __future__ import annotations

import sys
from dataclasses import dataclass

from offline_translator.call_bridge.contracts import EndpointFlow

DEVICE_STATE_ACTIVE = 1
DEVICE_DESCRIPTION_PROPERTY = "{a45c254e-df1c-4efd-8020-67d146a850e0},2"
ADAPTER_FRIENDLY_NAME_PROPERTY = "{b3f8fa53-0004-438e-9003-51a46e139bfc},6"


@dataclass(frozen=True, slots=True)
class NativeEndpointIdentity:
    endpoint_id: str
    flow: EndpointFlow
    aliases: tuple[str, ...]


def list_windows_endpoint_identities() -> list[NativeEndpointIdentity]:
    """Read active MMDevice endpoint IDs without opening an audio endpoint."""
    if sys.platform != "win32":
        raise RuntimeError("Native Windows endpoint identity requires Windows")
    import winreg

    base = r"SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio"
    result: list[NativeEndpointIdentity] = []
    for flow, registry_name in (
        (EndpointFlow.CAPTURE, "Capture"),
        (EndpointFlow.RENDER, "Render"),
    ):
        path = f"{base}\\{registry_name}"
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as flow_key:
            for index in range(winreg.QueryInfoKey(flow_key)[0]):
                opaque_id = winreg.EnumKey(flow_key, index)
                with winreg.OpenKey(flow_key, opaque_id) as endpoint_key:
                    try:
                        state = int(winreg.QueryValueEx(endpoint_key, "DeviceState")[0])
                    except OSError:
                        continue
                    if not state & DEVICE_STATE_ACTIVE:
                        continue
                    aliases = _read_aliases(winreg, endpoint_key)
                    if not aliases:
                        continue
                    result.append(
                        NativeEndpointIdentity(
                            endpoint_id=f"windows-mmdevice:v1:{flow.value}:{opaque_id}",
                            flow=flow,
                            aliases=aliases,
                        )
                    )
    return result


def _read_aliases(winreg, endpoint_key) -> tuple[str, ...]:
    try:
        properties = winreg.OpenKey(endpoint_key, "Properties")
    except OSError:
        return ()
    with properties:
        description = _read_string(winreg, properties, DEVICE_DESCRIPTION_PROPERTY)
        adapter = _read_string(winreg, properties, ADAPTER_FRIENDLY_NAME_PROPERTY)
    aliases = []
    if description:
        aliases.append(description)
    if description and adapter:
        aliases.append(f"{description} ({adapter})")
    return tuple(dict.fromkeys(aliases))


def _read_string(winreg, key, property_name: str) -> str | None:
    try:
        value = winreg.QueryValueEx(key, property_name)[0]
    except OSError:
        return None
    return value.strip() if isinstance(value, str) and value.strip() else None
