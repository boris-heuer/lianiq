from __future__ import annotations

import pytest

from lianiq.audio.endpoints import EndpointInventory, enumerate_endpoint_refs
from lianiq.audio.windows_endpoints import NativeEndpointIdentity, wasapi_default_indices
from lianiq.call_bridge.contracts import EndpointFlow

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


TWINS = [
    NativeEndpointIdentity("windows-mmdevice:v1:capture:a", EndpointFlow.CAPTURE, ("Headset",)),
    NativeEndpointIdentity("windows-mmdevice:v1:capture:b", EndpointFlow.CAPTURE, ("Headset",)),
]
TWIN_DEVICES = [device("Headset", 1, 0, index=4), device("Headset", 1, 0, index=6)]


def test_ac15_positional_policy_gives_duplicates_distinct_ids() -> None:
    refs = enumerate_endpoint_refs(
        TWIN_DEVICES, HOST_APIS, TWINS, require_native_identity=True, ambiguous="positional"
    )
    ids = [ref.endpoint_id for ref in refs]
    assert len(set(ids)) == 2 and ids[0].endswith("#1") and ids[1].endswith("#2")
    assert all(i.startswith("audio-endpoint:v1:capture:") for i in ids)
    assert [ref.runtime_index for ref in refs] == [4, 6]
    assert len(EndpointInventory(refs).endpoints) == 2


def test_ac15_call_bridge_default_still_fails_closed_for_the_same_inventory() -> None:
    with pytest.raises(ValueError, match="ambiguous"):
        enumerate_endpoint_refs(TWIN_DEVICES, HOST_APIS, TWINS, require_native_identity=True)


def test_ac22a_positional_policy_drops_a_stale_entry_without_identity() -> None:
    refs = enumerate_endpoint_refs(
        [device("Gone", 1, 0, index=1), *TWIN_DEVICES],
        HOST_APIS,
        TWINS,
        require_native_identity=True,
        ambiguous="positional",
    )
    assert [ref.display_name for ref in refs] == ["Headset", "Headset"]


def test_unknown_ambiguity_policy_is_rejected() -> None:
    with pytest.raises(ValueError, match="ambiguous policy"):
        enumerate_endpoint_refs([], HOST_APIS, ambiguous="first")


def test_wasapi_default_indices_per_flow() -> None:
    apis = [
        {"name": "MME", "default_input_device": 0, "default_output_device": 1},
        {"name": "Windows WASAPI", "default_input_device": 7, "default_output_device": -1},
    ]
    assert wasapi_default_indices(apis) == {EndpointFlow.CAPTURE: 7, EndpointFlow.RENDER: None}
    assert wasapi_default_indices(apis[:1]) == {
        EndpointFlow.CAPTURE: None,
        EndpointFlow.RENDER: None,
    }
