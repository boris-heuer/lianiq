"""Shared Call Bridge test data: sessions, a ready row-7 catalog and endpoint mappings."""

from __future__ import annotations

from pathlib import Path

from lianiq.call_bridge.contracts import AudioEndpointRef, EndpointFlow, EndpointRole
from lianiq.languages import (
    BUILTIN_REGISTRY,
    CALL_BRIDGE_MODE,
    CapabilityCatalog,
    LanguageId,
    LanguageRegistry,
    SessionPair,
)
from tests.languages.synthetic import provisioned_catalog

DE = LanguageId("de")
ZH = LanguageId("zh-Hans")


def call_bridge_session(
    local: str = DE,
    pair: tuple[str, str] = (DE, ZH),
    registry: LanguageRegistry = BUILTIN_REGISTRY,
) -> SessionPair:
    return SessionPair(registry.pair(*pair), CALL_BRIDGE_MODE, local_language=LanguageId(local))


def ready_catalog(
    root: Path,
    session: SessionPair,
    registry: LanguageRegistry = BUILTIN_REGISTRY,
    *,
    voices: tuple[str, ...] | None = None,
) -> CapabilityCatalog:
    """Every row-7 model of ``session`` present on disk, except voices left out of ``voices``."""
    a, b = session.pair.members
    return provisioned_catalog(
        root,
        registry,
        recognition=(a, b),
        edges=(f"{a}>{b}", f"{b}>{a}"),
        voices=(a, b) if voices is None else voices,
    )


def endpoint(role: EndpointRole, index: int) -> AudioEndpointRef:
    flow = (
        EndpointFlow.CAPTURE
        if role in {EndpointRole.LOCAL_MICROPHONE, EndpointRole.CALL_SPEAKER_CAPTURE}
        else EndpointFlow.RENDER
    )
    return AudioEndpointRef(f"id-{role.value}", f"Device {role.value}", flow, "WASAPI", index)


def mapping() -> dict[EndpointRole, AudioEndpointRef]:
    return {role: endpoint(role, index) for index, role in enumerate(EndpointRole)}
