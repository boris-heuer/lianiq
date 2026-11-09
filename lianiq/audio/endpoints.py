from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence

from lianiq.audio.windows_endpoints import (
    NativeEndpointIdentity,
    list_windows_endpoint_identities,
)
from lianiq.call_bridge.contracts import AudioEndpointRef, EndpointFlow


def enumerate_endpoint_refs(
    devices: Sequence[Mapping[str, object]],
    host_apis: Sequence[Mapping[str, object]],
    native_identities: Sequence[NativeEndpointIdentity] = (),
    *,
    require_native_identity: bool = False,
    ambiguous: str = "raise",
) -> list[AudioEndpointRef]:
    """One reference per device and flow with channels.

    ``ambiguous="raise"`` (Call Bridge, fail-closed) raises when several native identities
    match one display name. ``ambiguous="positional"`` (Conversation, CAP-0168 contract §4)
    assigns no native ID to such entries but the positional ID
    ``audio-endpoint:v1:<flow>:<digest>#<n>`` in enumeration order; the digest includes the
    number of same-named entries, so a positional ID resolves only while that number is
    unchanged. With ``require_native_identity`` an entry without any native match (stale
    after unplug) is then dropped instead of raising.
    """
    if ambiguous not in ("raise", "positional"):
        raise ValueError(f"Unsupported ambiguous policy: {ambiguous!r}")
    positional = ambiguous == "positional"
    endpoints: list[AudioEndpointRef] = []
    duplicates = _duplicate_counts(devices) if positional else {}
    seen: dict[str, int] = {}
    for position, raw in enumerate(devices):
        runtime_index = int(raw.get("index", position))
        host_api_index = int(raw["hostapi"])
        host_api = str(host_apis[host_api_index]["name"])
        display_name = str(raw["name"])
        sample_rate = round(float(raw["default_samplerate"]))
        for flow, channel_key in (
            (EndpointFlow.CAPTURE, "max_input_channels"),
            (EndpointFlow.RENDER, "max_output_channels"),
        ):
            channels = int(raw[channel_key])
            if channels <= 0:
                continue
            ambiguous_name = False
            try:
                native = _match_native_identity(display_name, flow, native_identities)
            except ValueError:
                if not positional:
                    raise
                native, ambiguous_name = None, True
            if require_native_identity and native is None and not ambiguous_name:
                if positional:
                    continue  # a stale PortAudio entry: dropped, never an error
                raise ValueError(
                    "Windows audio endpoint could not be mapped to one unambiguous MMDevice ID: "
                    f"{display_name!r} ({flow.value})"
                )
            signature = {
                "host_api": host_api.casefold(),
                "name": " ".join(display_name.casefold().split()),
                "flow": flow.value,
                "channels": channels,
                "sample_rate": sample_rate,
            }
            if ambiguous_name:
                signature["duplicates"] = duplicates[(_normalize_name(display_name), flow.value)]
            digest = hashlib.sha256(
                json.dumps(signature, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()[:20]
            endpoint_id = f"audio-endpoint:v1:{flow.value}:{digest}"
            if native is not None:
                endpoint_id = native.endpoint_id
            elif ambiguous_name:
                count = seen[endpoint_id] = seen.get(endpoint_id, 0) + 1
                endpoint_id = f"{endpoint_id}#{count}"
            endpoints.append(
                AudioEndpointRef(
                    endpoint_id=endpoint_id,
                    display_name=display_name,
                    flow=flow,
                    host_api=host_api,
                    runtime_index=runtime_index,
                    channels=channels,
                    sample_rate=sample_rate,
                )
            )
    return endpoints


def _duplicate_counts(devices: Sequence[Mapping[str, object]]) -> dict[tuple[str, str], int]:
    """How many PortAudio entries share each (normalized name, flow)."""
    counts: dict[tuple[str, str], int] = {}
    for raw in devices:
        for flow, channel_key in (
            (EndpointFlow.CAPTURE, "max_input_channels"),
            (EndpointFlow.RENDER, "max_output_channels"),
        ):
            if int(raw[channel_key]) > 0:
                key = (_normalize_name(str(raw["name"])), flow.value)
                counts[key] = counts.get(key, 0) + 1
    return counts


def _match_native_identity(
    display_name: str,
    flow: EndpointFlow,
    identities: Sequence[NativeEndpointIdentity],
) -> NativeEndpointIdentity | None:
    normalized = _normalize_name(display_name)
    candidates = [
        identity
        for identity in identities
        if identity.flow is flow
        and any(_names_match(normalized, _normalize_name(alias)) for alias in identity.aliases)
    ]
    if len(candidates) > 1:
        raise ValueError(
            f"Windows audio endpoint identity is ambiguous for {display_name!r} ({flow.value})"
        )
    return candidates[0] if candidates else None


def _normalize_name(value: str) -> str:
    return " ".join(value.casefold().split())


def _names_match(first: str, second: str) -> bool:
    if first == second:
        return True
    shorter, longer = sorted((first, second), key=len)
    return len(shorter) >= 12 and longer.startswith(shorter)


class EndpointInventory:
    def __init__(self, endpoints: Iterable[AudioEndpointRef]) -> None:
        self._by_id: dict[str, AudioEndpointRef] = {}
        for endpoint in endpoints:
            if endpoint.endpoint_id in self._by_id:
                first = self._by_id[endpoint.endpoint_id]
                raise ValueError(
                    "Audio endpoint identity is ambiguous: "
                    f"{first.display_name!r} has indistinguishable {endpoint.flow.value} devices"
                )
            self._by_id[endpoint.endpoint_id] = endpoint

    @property
    def endpoints(self) -> tuple[AudioEndpointRef, ...]:
        return tuple(self._by_id.values())

    def resolve(self, endpoint_id: str, flow: EndpointFlow) -> AudioEndpointRef:
        endpoint = self._by_id.get(endpoint_id)
        if endpoint is None or endpoint.flow is not flow:
            raise LookupError(f"Configured {flow.value} endpoint is not available: {endpoint_id}")
        return endpoint


def list_audio_endpoints() -> EndpointInventory:
    try:
        import sounddevice as sd
    except ImportError as exc:
        raise RuntimeError("sounddevice is not installed") from exc
    host_apis = list(sd.query_hostapis())
    devices = [
        dict(device, index=index)
        for index, device in enumerate(sd.query_devices())
        if "wasapi" in str(host_apis[int(device["hostapi"])]["name"]).casefold()
    ]
    native_identities = list_windows_endpoint_identities()
    endpoints = enumerate_endpoint_refs(
        devices,
        host_apis,
        native_identities,
        require_native_identity=True,
    )
    if not endpoints:
        raise RuntimeError("No Windows WASAPI audio endpoints are available")
    return EndpointInventory(endpoints)
