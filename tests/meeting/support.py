"""Shared meeting test data: a fake clock, endpoints and the de/zh-Hans pair (CAP-0177)."""

from __future__ import annotations

from lianiq.call_bridge.contracts import AudioEndpointRef, EndpointFlow
from lianiq.languages import BUILTIN_REGISTRY, LanguageId, LanguagePair

DE = LanguageId("de")
ZH = LanguageId("zh-Hans")
DE_ZH: LanguagePair = BUILTIN_REGISTRY.pair(DE, ZH)


class FakeClock:
    """A monotonic clock in seconds that only moves when a test advances it."""

    def __init__(self, start: float = 100.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance_ms(self, milliseconds: float) -> None:
        self.now += milliseconds / 1000.0


def endpoint(
    name: str,
    flow: EndpointFlow,
    endpoint_id: str | None = None,
    runtime_index: int = 0,
) -> AudioEndpointRef:
    return AudioEndpointRef(
        endpoint_id=endpoint_id or f"{flow.value}:{name}",
        display_name=name,
        flow=flow,
        host_api="Windows WASAPI",
        runtime_index=runtime_index,
    )


def capture(name: str, endpoint_id: str | None = None) -> AudioEndpointRef:
    return endpoint(name, EndpointFlow.CAPTURE, endpoint_id)


def render(name: str, endpoint_id: str | None = None) -> AudioEndpointRef:
    return endpoint(name, EndpointFlow.RENDER, endpoint_id)
