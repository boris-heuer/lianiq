"""Refresh strategy, timing and legacy migration of the device selection (CAP-0168 WI-04).

Qt-free Unit tests: AC-13 (refresh while stopped / identity monitor while running),
AC-22 (contract §7 precedence and saving), AC-22a (hot-plug Refresh, no full refresh while
a stream is open, stale PortAudio entries) and the spec §6.1 Refresh timing NFR.
"""

from __future__ import annotations

import json
import time

from lianiq.audio.device_inventory import conversation_inventory
from lianiq.audio.device_selection import (
    FOLLOW_DEFAULT,
    DeviceChoice,
    DevicePolicy,
    choice_from_settings,
    display_labels,
    is_legacy,
    resolve_choice,
    store_choice,
)
from lianiq.audio.device_state import DeviceState
from lianiq.audio.windows_endpoints import NativeEndpointIdentity
from lianiq.config import AppConfig, AudioConfig
from tests._fake_devices import CAPTURE, RENDER, FakeDevices, mic, native_id, speakers

HEADSET = mic("USB Headset", 3, "headset")
DESK = mic("Desk microphone", 4, "desk")
SPEAKERS = speakers("Desk speakers", 5, "spk")


def state_for(fake: FakeDevices) -> DeviceState:
    state = DeviceState(fake.read, fake.reinitialize, fake.read_native)
    state.load()
    return state


# AC-13 / AC-22a: the refresh strategy -----------------------------------------------------


def test_ac22a_refresh_while_stopped_lists_a_hot_plugged_headset() -> None:
    fake = FakeDevices(DESK, SPEAKERS)
    state = state_for(fake)
    assert fake.reinitialized == 0  # the start-up read needs no re-initialisation
    fake.set(DESK, SPEAKERS, HEADSET)

    change = state.refresh(streams_open=False)

    assert fake.reinitialized == 1  # spec §9 T5: one PortAudio re-initialisation
    assert change.added == ("USB Headset",) and not state.refresh_pending
    resolved = resolve_choice(
        DeviceChoice(DevicePolicy.EXPLICIT, HEADSET.endpoint_id),
        state.inventory.endpoints,
        CAPTURE,
        None,
    )
    assert resolved.endpoint == HEADSET


def test_ac13_while_a_stream_is_open_only_identities_are_compared() -> None:
    fake = FakeDevices(HEADSET, DESK, SPEAKERS)
    state = state_for(fake)
    fake.unplug(HEADSET)

    change = state.refresh(streams_open=True)  # guarded Refresh during a session

    assert fake.reinitialized == 0 and fake.reads == 1  # no full refresh, no PortAudio read
    assert change.removed == ("USB Headset",) and state.refresh_pending
    assert HEADSET in state.inventory.endpoints  # the active lists do not change
    assert not state.present(HEADSET.endpoint_id) and state.present(DESK.endpoint_id)
    assert state.check_identities().is_empty()  # reported once

    fake.set(DESK, SPEAKERS)
    after = state.after_stop()  # the full refresh runs when the last stream closed

    assert after is not None and fake.reinitialized == 1
    assert [e.endpoint_id for e in state.inventory.endpoints] == [
        DESK.endpoint_id,
        SPEAKERS.endpoint_id,
    ]
    assert state.after_stop() is None  # nothing pending any more


def test_ac13_full_refresh_reports_reorder_and_default_change() -> None:
    fake = FakeDevices(HEADSET, DESK, defaults={CAPTURE: HEADSET.endpoint_id})
    state = state_for(fake)
    moved = (mic("Desk microphone", 1, "desk"), mic("USB Headset", 2, "headset"))
    fake.set(*moved, defaults={CAPTURE: DESK.endpoint_id})

    change = state.refresh(streams_open=False)

    assert change.reordered and change.default_changed and not change.added
    saved = DeviceChoice(DevicePolicy.EXPLICIT, HEADSET.endpoint_id, "USB Headset")
    inventory = state.inventory
    assert resolve_choice(saved, inventory.endpoints, CAPTURE, None).endpoint.runtime_index == 2


def test_ac22a_unreadable_native_identities_never_count_as_loss() -> None:
    def fail():
        raise RuntimeError("Native Windows endpoint identity requires Windows")

    state = DeviceState(FakeDevices(HEADSET).read, lambda: None, fail)
    state.load()
    assert state.check_identities().is_empty() and state.present(HEADSET.endpoint_id)


def test_ac22a_stale_portaudio_entry_is_dropped_instead_of_failing() -> None:
    apis = [{"name": "Windows WASAPI"}]
    rows = [
        {
            "name": n,
            "max_input_channels": 1,
            "max_output_channels": 0,
            "default_samplerate": 48_000,
            "hostapi": 0,
            "index": i,
        }
        for i, n in enumerate(("USB Headset", "Unplugged mic"))
    ]
    natives = [NativeEndpointIdentity(native_id(CAPTURE, "h"), CAPTURE, ("USB Headset",))]
    inventory = conversation_inventory(rows, apis, natives)
    assert [e.display_name for e in inventory.endpoints] == ["USB Headset"]


def test_refresh_with_fifty_endpoints_is_under_100_ms() -> None:
    endpoints = [mic(f"Microphone {n}", n, f"m{n}") for n in range(25)]
    endpoints += [speakers(f"Speakers {n}", 25 + n, f"s{n}") for n in range(25)]
    fake = FakeDevices(*endpoints)
    state = state_for(fake)
    started = time.perf_counter()
    state.refresh(streams_open=False)
    for flow in (CAPTURE, RENDER):
        display_labels(state.inventory.endpoints)
        resolve_choice(
            FOLLOW_DEFAULT, state.inventory.endpoints, flow, state.inventory.default(flow)
        )
    assert time.perf_counter() - started < 0.1


# AC-22: contract §7 precedence and saving -----------------------------------------------


def test_ac22_policy_key_wins_over_the_legacy_index() -> None:
    audio = AudioConfig(
        input_device=7,
        input_policy="explicit",
        input_endpoint_id=HEADSET.endpoint_id,
        input_device_name="USB Headset",
    )
    choice = choice_from_settings(audio, CAPTURE, {7: "Desk microphone"}, [HEADSET, DESK])
    assert choice == DeviceChoice(DevicePolicy.EXPLICIT, HEADSET.endpoint_id, "USB Headset")
    assert not is_legacy(audio, CAPTURE)


def test_ac22_no_policy_and_no_index_follows_the_default() -> None:
    assert choice_from_settings(AudioConfig(), RENDER, {}, [SPEAKERS]) == FOLLOW_DEFAULT


def test_ac22_unique_legacy_name_becomes_explicit_identity() -> None:
    audio = AudioConfig(input_device=7)
    # MME truncates names to 31 characters; ``_names_match`` accepts the prefix.
    names = {7: "Microphone (USB Headset Pro"}
    long = mic("Microphone (USB Headset Pro Wireless)", 3, "pro")
    assert is_legacy(audio, CAPTURE)
    assert choice_from_settings(audio, CAPTURE, names, [long, DESK]) == DeviceChoice(
        DevicePolicy.EXPLICIT, long.endpoint_id, long.display_name
    )


def test_ac22_ambiguous_or_missing_legacy_name_stays_unavailable() -> None:
    audio = AudioConfig(input_device=7)
    twins = [mic("USB Headset", 3, "a"), mic("USB Headset", 4, "b")]
    choice = choice_from_settings(audio, CAPTURE, {7: "USB Headset"}, twins)
    assert choice == DeviceChoice(DevicePolicy.EXPLICIT, None, "USB Headset")
    assert resolve_choice(choice, twins, CAPTURE, twins[0]).label == "USB Headset — unavailable"
    gone = choice_from_settings(audio, CAPTURE, {7: "Old mic"}, [DESK])
    assert gone.endpoint_id is None and gone.display_name == "Old mic"
    unknown = choice_from_settings(audio, CAPTURE, {}, [DESK])
    assert unknown.endpoint_id is None


def test_ac22_saving_writes_the_new_keys_and_nulls_the_indices(tmp_path) -> None:
    config = AppConfig()
    config.audio.input_device, config.audio.output_device = 3, 5
    store_choice(config.audio, CAPTURE, DeviceChoice(DevicePolicy.EXPLICIT, "id", "Mic"))
    store_choice(config.audio, RENDER, FOLLOW_DEFAULT)
    path = tmp_path / "settings.local.json"
    config.save(path)

    audio = json.loads(path.read_text(encoding="utf-8"))["audio"]
    assert audio["input_device"] is None and audio["output_device"] is None
    assert (audio["input_policy"], audio["input_endpoint_id"]) == ("explicit", "id")
    assert audio["input_device_name"] == "Mic"
    assert (audio["output_policy"], audio["output_endpoint_id"]) == ("follow_default", None)
    reloaded = AppConfig.load(path).audio
    assert choice_from_settings(reloaded, CAPTURE, {}, []) == DeviceChoice(
        DevicePolicy.EXPLICIT, "id", "Mic"
    )
