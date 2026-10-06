from __future__ import annotations

import pytest

from offline_translator.audio.endpoints import EndpointInventory, enumerate_endpoint_refs
from offline_translator.audio.windows_endpoints import NativeEndpointIdentity
from offline_translator.call_bridge.contracts import EndpointFlow

HOST_APIS = [{"name": "Windows WASAPI"}]


def device(name, inputs, outputs, rate=48_000, index=0):
    return {
        "name": name,
        "max_input_channels": inputs,
        "max_output_channels": outputs,
        "default_samplerate": rate,
        "hostapi": 0,
        "index": index,
    }


def test_stable_reference_survives_runtime_index_reorder() -> None:
    native = [
        NativeEndpointIdentity(
            "windows-mmdevice:v1:capture:opaque", EndpointFlow.CAPTURE, ("Cable",)
        )
    ]
    first = enumerate_endpoint_refs(
        [device("Cable", 2, 0, index=3)], HOST_APIS, native, require_native_identity=True
    )[0]
    second = enumerate_endpoint_refs(
        [device("Cable", 2, 0, index=9)], HOST_APIS, native, require_native_identity=True
    )[0]

    assert first.endpoint_id == second.endpoint_id
    assert first.runtime_index == 3
    assert second.runtime_index == 9


def test_missing_native_identity_fails_closed_when_required() -> None:
    with pytest.raises(ValueError, match="MMDevice ID"):
        enumerate_endpoint_refs(
            [device("Cable", 2, 0, index=3)],
            HOST_APIS,
            require_native_identity=True,
        )


def test_same_display_name_with_different_capabilities_is_unambiguous() -> None:
    refs = enumerate_endpoint_refs(
        [device("Cable", 1, 0, index=1), device("Cable", 2, 0, index=2)], HOST_APIS
    )
    assert len({ref.endpoint_id for ref in refs}) == 2


def test_indistinguishable_duplicate_is_rejected() -> None:
    refs = enumerate_endpoint_refs(
        [device("Cable", 2, 0, index=1), device("Cable", 2, 0, index=2)], HOST_APIS
    )
    with pytest.raises(ValueError, match="ambiguous"):
        EndpointInventory(refs)


def test_resolve_missing_endpoint_never_uses_default() -> None:
    ref = enumerate_endpoint_refs([device("Cable", 2, 0, index=1)], HOST_APIS)[0]
    inventory = EndpointInventory([ref])
    with pytest.raises(LookupError, match="not available"):
        inventory.resolve("missing", EndpointFlow.CAPTURE)
