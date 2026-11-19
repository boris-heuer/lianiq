"""PortAudio names with a Bluetooth or driver suffix that Windows does not store (#136).

All names are synthetic: "Headphones (Synthetic Model)" stands for the PortAudio name
"<description> (<model>)", the aliases for the Windows names "<description>" and
"<description> (<driver> ...)".
"""

from __future__ import annotations

import pytest

from lianiq.audio.device_inventory import conversation_inventory
from lianiq.audio.endpoints import _strip_suffix, enumerate_endpoint_refs
from lianiq.audio.windows_endpoints import NativeEndpointIdentity
from lianiq.call_bridge.contracts import EndpointFlow

CAPTURE, RENDER = EndpointFlow.CAPTURE, EndpointFlow.RENDER
HOST_APIS = [{"name": "Windows WASAPI", "default_input_device": 0, "default_output_device": 1}]
HEADSET = "Headphones (Synthetic Model)"


def device(name, inputs, outputs, index):
    return {
        "name": name,
        "max_input_channels": inputs,
        "max_output_channels": outputs,
        "default_samplerate": 48_000,
        "hostapi": 0,
        "index": index,
    }


def bluetooth(flow: EndpointFlow, key: str = "bt") -> NativeEndpointIdentity:
    kind = "Capture" if flow is CAPTURE else "Render"
    aliases = ("Headphones", f"Headphones (Synthetic Driver Bluetooth {kind} Audio Device)")
    return NativeEndpointIdentity(f"windows-mmdevice:v1:{flow.value}:{key}", flow, aliases)


def refs(rows, natives, ambiguous="positional", suffix_match=True):
    return enumerate_endpoint_refs(
        rows,
        HOST_APIS,
        natives,
        require_native_identity=True,
        ambiguous=ambiguous,
        suffix_match=suffix_match,
    )


BUILT_IN = NativeEndpointIdentity(
    "windows-mmdevice:v1:capture:built-in", CAPTURE, ("Microphone", "Microphone (Synthetic Audio)")
)
NATIVES = [bluetooth(CAPTURE), bluetooth(RENDER), BUILT_IN]
DEVICES = [
    device(HEADSET, 1, 0, 0),
    device(HEADSET, 0, 2, 1),
    device("Microphone (Synthetic Audio)", 2, 0, 2),
]


@pytest.mark.parametrize("ambiguous", ["raise", "positional"])
def test_bluetooth_suffix_matches_capture_and_render(ambiguous) -> None:
    found = refs(DEVICES, NATIVES, ambiguous)
    assert [(r.endpoint_id, r.display_name, r.runtime_index) for r in found] == [
        ("windows-mmdevice:v1:capture:bt", HEADSET, 0),
        ("windows-mmdevice:v1:render:bt", HEADSET, 1),
        ("windows-mmdevice:v1:capture:built-in", "Microphone (Synthetic Audio)", 2),
    ]


def test_suffix_match_is_off_unless_the_caller_has_a_fresh_list() -> None:
    """A stale list (the Call Bridge never re-initialises PortAudio) keeps tier-1 matching:
    a gone headset's entry never takes the ID of a new device with the same description."""
    rows = [device(HEADSET, 0, 2, 0), device("Speakers (Synthetic Onboard)", 0, 2, 1)]
    other = NativeEndpointIdentity(
        "windows-mmdevice:v1:render:other", RENDER, ("Headphones", "Headphones (Other Adapter)")
    )
    onboard = NativeEndpointIdentity(
        "windows-mmdevice:v1:render:onboard", RENDER, ("Speakers", "Speakers (Synthetic Onboard)")
    )
    with pytest.raises(ValueError, match="MMDevice ID"):
        refs(rows, [other, onboard], "raise", suffix_match=False)
    found = refs(rows, [other, onboard], suffix_match=False)
    assert [r.endpoint_id for r in found] == ["windows-mmdevice:v1:render:onboard"]


def test_conversation_inventory_lists_the_headset_and_resolves_the_defaults() -> None:
    inventory = conversation_inventory(DEVICES, HOST_APIS, NATIVES)
    assert inventory.default(RENDER).endpoint_id == "windows-mmdevice:v1:render:bt"
    assert inventory.default(CAPTURE).endpoint_id == "windows-mmdevice:v1:capture:bt"
    # No unusable look-alike: a row is never tied to the other flow's identity.
    assert len(inventory.endpoints) == 3


def test_duplicate_suffixed_names_stay_unmapped() -> None:
    twins = [device(HEADSET, 1, 0, 0), device(HEADSET, 1, 0, 3)]
    natives = [bluetooth(CAPTURE, "a"), bluetooth(CAPTURE, "b")]
    assert refs(twins, natives) == []  # dropped, never guessed
    with pytest.raises(ValueError, match="MMDevice ID"):
        refs(twins, natives, "raise")


def test_two_free_identities_for_one_suffixed_name_stay_unmapped() -> None:
    natives = [bluetooth(CAPTURE, "a"), bluetooth(CAPTURE, "b")]
    assert refs([device(HEADSET, 1, 0, 0)], natives) == []


def test_two_suffixed_names_for_one_identity_stay_unmapped() -> None:
    rows = [device(HEADSET, 1, 0, 0), device("Headphones (Other Synthetic Model)", 1, 0, 1)]
    assert refs(rows, [bluetooth(CAPTURE)]) == []


def test_an_identity_named_by_another_entry_is_never_offered_to_the_suffix_match() -> None:
    exact = device("Headphones (Synthetic Driver Bluetooth Capture Audio Device)", 1, 0, 0)
    rows = [exact, device(HEADSET, 1, 0, 1)]
    # Only one identity: the exact entry has it, the suffixed entry gets nothing.
    assert [r.runtime_index for r in refs(rows, [bluetooth(CAPTURE, "a")])] == [0]
    # A second identity with the same base is then the one-to-one partner.
    other = NativeEndpointIdentity("windows-mmdevice:v1:capture:b", CAPTURE, ("Headphones",))
    found = refs(rows, [bluetooth(CAPTURE, "a"), other], "raise")
    assert [(r.endpoint_id, r.runtime_index) for r in found] == [
        ("windows-mmdevice:v1:capture:a", 0),
        ("windows-mmdevice:v1:capture:b", 1),
    ]


def test_suffix_match_never_crosses_flows() -> None:
    assert refs([device(HEADSET, 0, 2, 0)], [bluetooth(CAPTURE)]) == []


@pytest.mark.parametrize(
    ("name", "base"),
    [
        ("headphones (synthetic model)", "headphones"),
        ("headphones", "headphones"),
        ("line (a) (b)", "line (a)"),
        ("(only)", "(only)"),
    ],
)
def test_strip_suffix(name, base) -> None:
    assert _strip_suffix(name) == base
