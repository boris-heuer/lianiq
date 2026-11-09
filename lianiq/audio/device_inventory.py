"""The Conversation device inventory read from PortAudio and Windows (CAP-0168 contract §4).

Qt-free. ``read_inventory`` lists the WASAPI endpoints with the positional identity for
duplicate names (``enumerate_endpoint_refs(..., ambiguous="positional")``), the WASAPI
default endpoint of each flow and the names of the full PortAudio list (all host APIs) for
the legacy-index migration (contract §7). ``reinitialize_portaudio`` is the one wrapper of
sounddevice's private re-initialisation (spec §9 T5); it runs only while no stream is open.

An endpoint present in Windows whose PortAudio entry has no channel for its flow is listed
as an ``UnusableEndpoint`` (AC-17): ``AudioEndpointRef`` (shared with the Call Bridge)
requires channels > 0, so the unusable entry is a separate look-alike record.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from lianiq.audio.endpoints import _match_native_identity, enumerate_endpoint_refs
from lianiq.audio.windows_endpoints import (
    NativeEndpointIdentity,
    list_windows_endpoint_identities,
    wasapi_default_indices,
)
from lianiq.call_bridge.contracts import AudioEndpointRef, EndpointFlow

_CHANNEL_KEYS = {
    EndpointFlow.CAPTURE: "max_input_channels",
    EndpointFlow.RENDER: "max_output_channels",
}


@dataclass(frozen=True, slots=True)
class UnusableEndpoint:
    """A present endpoint whose PortAudio entry has no channel for ``flow``; never opened."""

    endpoint_id: str
    display_name: str
    flow: EndpointFlow
    host_api: str
    runtime_index: int
    channels: int = 0
    sample_rate: int = 48_000


ConversationEndpoint = AudioEndpointRef | UnusableEndpoint


@dataclass(frozen=True)
class ConversationInventory:
    endpoints: tuple[ConversationEndpoint, ...] = ()
    # The endpoint ID of each flow's Windows default, ``None`` when there is none.
    defaults: Mapping[EndpointFlow, str | None] = field(default_factory=dict)
    # Runtime index -> name over the full PortAudio list (all host APIs), contract §7.
    legacy_names: Mapping[int, str] = field(default_factory=dict)

    def default(self, flow: EndpointFlow) -> ConversationEndpoint | None:
        endpoint_id = self.defaults.get(flow)
        return next(
            (e for e in self.endpoints if e.endpoint_id == endpoint_id and e.flow is flow), None
        )


def conversation_inventory(
    devices: Sequence[Mapping[str, object]],
    host_apis: Sequence[Mapping[str, object]],
    native_identities: Sequence[NativeEndpointIdentity],
) -> ConversationInventory:
    """Build the inventory from raw PortAudio rows (all host APIs) and native identities."""
    rows = [dict(raw, index=int(raw.get("index", i))) for i, raw in enumerate(devices)]
    wasapi = [row for row in rows if "wasapi" in _host_api(row, host_apis).casefold()]
    usable = enumerate_endpoint_refs(
        wasapi, host_apis, native_identities, require_native_identity=True, ambiguous="positional"
    )
    endpoints: list[ConversationEndpoint] = list(usable)
    known = {endpoint.endpoint_id for endpoint in usable}
    for row in wasapi:
        for flow, key in _CHANNEL_KEYS.items():
            if int(row[key]) > 0:
                continue
            try:
                native = _match_native_identity(str(row["name"]), flow, native_identities)
            except ValueError:
                continue  # ambiguous: no identity can be tied to this entry
            if native is None or native.endpoint_id in known:
                continue
            known.add(native.endpoint_id)
            endpoints.append(
                UnusableEndpoint(
                    native.endpoint_id,
                    str(row["name"]),
                    flow,
                    _host_api(row, host_apis),
                    int(row["index"]),
                    0,
                    round(float(row["default_samplerate"])),
                )
            )
    indices = wasapi_default_indices(host_apis)
    defaults = {
        flow: next(
            (e.endpoint_id for e in endpoints if e.flow is flow and e.runtime_index == index),
            None,
        )
        for flow, index in indices.items()
    }
    names = {int(row["index"]): str(row["name"]) for row in rows}
    return ConversationInventory(tuple(endpoints), defaults, names)


def _host_api(row: Mapping[str, object], host_apis: Sequence[Mapping[str, object]]) -> str:
    return str(host_apis[int(row["hostapi"])]["name"])


def _sounddevice():
    try:
        import sounddevice as sd
    except ImportError as exc:
        raise RuntimeError("sounddevice is not installed") from exc
    return sd


def read_inventory() -> ConversationInventory:
    """The current inventory; PortAudio's list is the one of its last initialisation."""
    sd = _sounddevice()
    host_apis = list(sd.query_hostapis())
    devices = [dict(device, index=index) for index, device in enumerate(sd.query_devices())]
    return conversation_inventory(devices, host_apis, list_windows_endpoint_identities())


def list_conversation_endpoints() -> tuple[ConversationEndpoint, ...]:
    return read_inventory().endpoints


def reinitialize_portaudio() -> None:
    """Re-read PortAudio's device list (private API of the pinned sounddevice 0.5.6, T5).

    Callers guarantee that no stream is open (contract §4 "Refresh strategy").
    """
    sd = _sounddevice()
    sd._terminate()
    sd._initialize()


def read_native_ids() -> dict[str, str]:
    """Active native endpoint ID -> name, read from Windows without touching PortAudio."""
    return {i.endpoint_id: i.aliases[0] for i in list_windows_endpoint_identities()}
