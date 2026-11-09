"""Device selection by endpoint identity (CAP-0168 contract §4; AC-13..AC-17 Unit).

Qt-free, over the D-07 fake devices (``tests/_fake_devices.py``). The refresh strategy,
the timing NFR and the legacy migration are in ``test_device_state.py``.
"""

from __future__ import annotations

import re

from lianiq.audio.device_inventory import UnusableEndpoint, conversation_inventory
from lianiq.audio.device_selection import (
    FOLLOW_DEFAULT,
    DeviceChoice,
    DevicePolicy,
    InventoryChange,
    describe,
    diff_inventory,
    diff_native,
    display_labels,
    resolve_choice,
)
from lianiq.audio.windows_endpoints import NativeEndpointIdentity
from tests._fake_devices import CAPTURE, RENDER, mic, native_id, speakers, unusable

HEADSET = mic("USB Headset", 3, "headset")
DESK = mic("Desk microphone", 4, "desk")
SPEAKERS = speakers("Desk speakers", 5, "desk-spk")
ENDPOINT_ID = re.compile(r"windows-mmdevice:|audio-endpoint:|\{0\.0\.")
HOST_APIS = [{"name": "MME"}, {"name": "Windows WASAPI"}]


def explicit(endpoint) -> DeviceChoice:
    return DeviceChoice(DevicePolicy.EXPLICIT, endpoint.endpoint_id, endpoint.display_name)


def row(name, inputs, outputs, index, hostapi=1):
    return {
        "name": name,
        "max_input_channels": inputs,
        "max_output_channels": outputs,
        "default_samplerate": 48_000,
        "hostapi": hostapi,
        "index": index,
    }


def identity(flow, key, name):
    return NativeEndpointIdentity(native_id(flow, key), flow, (name,))


# AC-13: identity survives reorder; the inventory change ---------------------------------


def test_ac13_saved_native_identity_stays_selected_regardless_of_order() -> None:
    moved = mic("USB Headset", 9, "headset")  # same identity, new runtime index
    resolved = resolve_choice(explicit(HEADSET), [DESK, moved], CAPTURE, DESK)
    assert resolved.available and resolved.usable
    assert resolved.endpoint == moved and resolved.endpoint.runtime_index == 9


def test_ac13_diff_reports_added_removed_reordered_and_default_by_label() -> None:
    plugged = mic("Headset", 6, "new")
    change = diff_inventory([HEADSET, DESK, SPEAKERS], [DESK, HEADSET, plugged], "a", "b")
    assert change.added == ("Headset",)
    assert change.removed == ("Desk speakers",)
    assert change.reordered and change.default_changed
    assert change.summary() == (
        "added 'Headset', removed 'Desk speakers', order changed, Windows default changed"
    )
    assert not ENDPOINT_ID.search(change.summary())
    assert diff_inventory([HEADSET], [HEADSET]).is_empty()


def test_ac13_identity_only_change_while_a_stream_is_open() -> None:
    known = {HEADSET.endpoint_id: "USB Headset", DESK.endpoint_id: "Desk microphone"}
    current = {DESK.endpoint_id: "Desk microphone", native_id(CAPTURE, "x"): "Headset"}
    change = diff_native([HEADSET, DESK], known, current)
    assert change == InventoryChange(added=("Headset",), removed=("USB Headset",))
    assert change.summary() == "added 'Headset', removed 'USB Headset'"


# AC-14: a missing explicit device stays unavailable ---------------------------------------


def test_ac14_missing_explicit_device_is_unavailable_and_never_replaced() -> None:
    resolved = resolve_choice(explicit(HEADSET), [DESK], CAPTURE, DESK)
    assert not resolved.available and not resolved.usable and resolved.endpoint is None
    assert resolved.label == "USB Headset — unavailable"
    unnamed = resolve_choice(DeviceChoice(DevicePolicy.EXPLICIT), [DESK], CAPTURE, DESK)
    assert unnamed.endpoint is None and unnamed.label == "Saved device — unavailable"


def test_ac14_an_identity_of_the_other_flow_never_resolves() -> None:
    wrong = DeviceChoice(DevicePolicy.EXPLICIT, SPEAKERS.endpoint_id, "Desk speakers")
    assert resolve_choice(wrong, [SPEAKERS, DESK], CAPTURE, DESK).endpoint is None


# AC-15: duplicate names --------------------------------------------------------------------


def test_ac15_duplicate_names_get_positional_ids_and_numbered_labels() -> None:
    natives = [identity(CAPTURE, "a", "Headset"), identity(CAPTURE, "b", "Headset")]
    inventory = conversation_inventory(
        [row("Headset", 1, 0, 2), row("Headset", 1, 0, 3), row("Headset", 1, 0, 7, 0)],
        HOST_APIS,
        natives,
    )
    first, second = inventory.endpoints
    assert first.endpoint_id.endswith("#1") and second.endpoint_id.endswith("#2")
    assert first.endpoint_id.startswith("audio-endpoint:v1:capture:")
    assert display_labels(inventory.endpoints) == {
        first.endpoint_id: "Headset",
        second.endpoint_id: "Headset (2)",
    }
    texts = [*display_labels(inventory.endpoints).values(), *map(describe, inventory.endpoints)]
    assert not any(ENDPOINT_ID.search(text) for text in texts)
    assert inventory.legacy_names == {2: "Headset", 3: "Headset", 7: "Headset"}  # all APIs


def test_ac15_positional_id_needs_the_same_number_of_same_named_endpoints() -> None:
    natives = [identity(CAPTURE, key, "Headset") for key in "abc"]
    two = conversation_inventory(
        [row("Headset", 1, 0, 2), row("Headset", 1, 0, 3)], HOST_APIS, natives[:2]
    )
    three = conversation_inventory(
        [row("Headset", 1, 0, 2), row("Headset", 1, 0, 3), row("Headset", 1, 0, 4)],
        HOST_APIS,
        natives,
    )
    saved = explicit(two.endpoints[1])
    assert resolve_choice(saved, two.endpoints, CAPTURE, None).endpoint is not None
    resolved = resolve_choice(saved, three.endpoints, CAPTURE, None)
    assert resolved.endpoint is None and resolved.label == "Headset — unavailable"


# AC-16: Follow Windows default -------------------------------------------------------------


def test_ac16_follow_default_names_the_current_default() -> None:
    resolved = resolve_choice(FOLLOW_DEFAULT, [HEADSET, DESK], CAPTURE, DESK)
    assert resolved.endpoint == DESK
    assert resolved.label == "Follow Windows default (now: Desk microphone)"
    changed = resolve_choice(FOLLOW_DEFAULT, [HEADSET, DESK], CAPTURE, HEADSET)
    assert changed.label == "Follow Windows default (now: USB Headset)"
    none = resolve_choice(FOLLOW_DEFAULT, [], CAPTURE, None)
    assert none.endpoint is None and none.label == "Follow Windows default (now: no device)"


def test_ac16_wasapi_default_indices_become_default_identities() -> None:
    apis = [
        {"name": "MME"},
        {"name": "Windows WASAPI", "default_input_device": 4, "default_output_device": -1},
    ]
    inventory = conversation_inventory(
        [row("Desk microphone", 1, 0, 4), row("Desk speakers", 0, 2, 5)],
        apis,
        [identity(CAPTURE, "desk", "Desk microphone"), identity(RENDER, "spk", "Desk speakers")],
    )
    assert inventory.default(CAPTURE).endpoint_id == native_id(CAPTURE, "desk")
    assert inventory.default(RENDER) is None


# AC-17: endpoints without usable channels --------------------------------------------------


def test_ac17_zero_channel_endpoint_is_listed_unusable_with_its_reason() -> None:
    inventory = conversation_inventory(
        [row("Line In (Dock)", 0, 0, 4), row("Desk speakers", 0, 2, 5)],
        HOST_APIS,
        [identity(CAPTURE, "line", "Line In (Dock)"), identity(RENDER, "spk", "Desk speakers")],
    )
    broken = next(e for e in inventory.endpoints if isinstance(e, UnusableEndpoint))
    assert broken.flow is CAPTURE and broken.channels == 0
    resolved = resolve_choice(explicit(broken), inventory.endpoints, CAPTURE, None)
    assert resolved.available and not resolved.usable and resolved.endpoint is None
    assert resolved.reason == "This device has no usable input channels"
    assert resolved.label == "Line In (Dock) — This device has no usable input channels"
    # The render endpoint of another device never becomes an unusable capture entry.
    assert [e.display_name for e in inventory.endpoints if e.flow is CAPTURE] == ["Line In (Dock)"]


def test_ac17_unusable_default_cannot_be_started() -> None:
    dead = unusable("Dead speakers", RENDER, 8)
    resolved = resolve_choice(FOLLOW_DEFAULT, [dead], RENDER, dead)
    assert resolved.endpoint is None and not resolved.usable
    assert resolved.reason == "This device has no usable output channels"
