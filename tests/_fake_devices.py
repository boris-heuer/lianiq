"""Fake Conversation devices and a fake clock (CAP-0168 e2e data D-07).

``FakeDevices`` stands in for the three reads of ``lianiq.ui.device_setup``: the PortAudio
inventory (``read_inventory``), its re-initialisation (``reinitialize_portaudio``) and the
live native identities (``read_native_ids``). ``unplug`` removes a native identity only, as
Windows does while PortAudio keeps its stale list until the next full refresh.
"""

from __future__ import annotations

from lianiq.audio.device_inventory import ConversationInventory, UnusableEndpoint
from lianiq.call_bridge.contracts import AudioEndpointRef, EndpointFlow

CAPTURE, RENDER = EndpointFlow.CAPTURE, EndpointFlow.RENDER
WASAPI = "Windows WASAPI"


def native_id(flow: EndpointFlow, key: str) -> str:
    return f"windows-mmdevice:v1:{flow.value}:{{0.0.0.00000000}}.{{{key}}}"


def mic(name: str, index: int = 0, key: str | None = None, channels: int = 1):
    return AudioEndpointRef(native_id(CAPTURE, key or name), name, CAPTURE, WASAPI, index, channels)


def speakers(name: str, index: int = 1, key: str | None = None, channels: int = 2):
    return AudioEndpointRef(native_id(RENDER, key or name), name, RENDER, WASAPI, index, channels)


def unusable(name: str, flow: EndpointFlow, index: int, key: str | None = None):
    return UnusableEndpoint(native_id(flow, key or name), name, flow, WASAPI, index)


MICROPHONE = mic("Test microphone", 0, "mic")
SPEAKERS = speakers("Test speakers", 1, "spk")


def first_usable(endpoints, flow: EndpointFlow) -> str | None:
    return next(
        (
            e.endpoint_id
            for e in endpoints
            if e.flow is flow and not isinstance(e, UnusableEndpoint)
        ),
        None,
    )


class FakeDevices:
    def __init__(self, *endpoints, defaults=None, legacy_names=None) -> None:
        self.reinitialized = 0
        self.reads = 0
        self.native_reads = 0
        self.set(*endpoints, defaults=defaults, legacy_names=legacy_names)

    def set(self, *endpoints, defaults=None, legacy_names=None) -> None:
        """A new PortAudio list (visible after the next full refresh) and live identities."""
        self.endpoints = tuple(endpoints)
        self.defaults = dict(
            defaults
            if defaults is not None
            else {flow: first_usable(endpoints, flow) for flow in (CAPTURE, RENDER)}
        )
        self.legacy_names = dict(
            legacy_names or {e.runtime_index: e.display_name for e in endpoints}
        )
        self.native = {
            e.endpoint_id: e.display_name
            for e in endpoints
            if e.endpoint_id.startswith("windows-mmdevice:")
        }

    def unplug(self, endpoint) -> None:
        self.native.pop(endpoint.endpoint_id, None)

    def read(self) -> ConversationInventory:
        """As ``conversation_inventory``: an entry whose native identity left is dropped."""
        self.reads += 1
        endpoints = tuple(
            e
            for e in self.endpoints
            if not e.endpoint_id.startswith("windows-mmdevice:") or e.endpoint_id in self.native
        )
        return ConversationInventory(endpoints, dict(self.defaults), dict(self.legacy_names))

    def reinitialize(self) -> None:
        self.reinitialized += 1

    def read_native(self) -> dict[str, str]:
        self.native_reads += 1
        return dict(self.native)

    def install(self, monkeypatch) -> FakeDevices:
        import lianiq.ui.device_setup as device_setup_module

        monkeypatch.setattr(device_setup_module, "read_inventory", self.read)
        monkeypatch.setattr(device_setup_module, "reinitialize_portaudio", self.reinitialize)
        monkeypatch.setattr(device_setup_module, "read_native_ids", self.read_native)
        return self


class FakeClock:
    def __init__(self, now: float = 100.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds
