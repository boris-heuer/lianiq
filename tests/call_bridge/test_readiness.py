"""CAP-0166 AC-02, AC-03, AC-16: every blocking reason of the Call Bridge Start gate."""

from __future__ import annotations

from lianiq.audio.endpoints import EndpointInventory
from lianiq.call_bridge.contracts import AudioEndpointRef, EndpointFlow, EndpointRole
from lianiq.call_bridge.controller import check_call_bridge
from lianiq.call_bridge.readiness import (
    ReadinessCode,
    configured_assignments,
    evaluate_readiness,
)
from lianiq.call_bridge.texts import ROLE_LABELS
from lianiq.config import AppConfig
from lianiq.config_migration import migrate_settings
from lianiq.languages import ModeAvailability
from tests.call_bridge.support import DE, call_bridge_session, ready_catalog

CAPTURE, RENDER = EndpointFlow.CAPTURE, EndpointFlow.RENDER
READY = ModeAvailability(True, ())
MIC, CALL_MIC, CALL_SPEAKER, PHONES = EndpointRole


def ref(endpoint_id: str, name: str, flow: EndpointFlow) -> AudioEndpointRef:
    return AudioEndpointRef(endpoint_id, name, flow, "WASAPI", 0)


DEVICES = (
    ref("mic", "Headset Microphone (Jabra Evolve)", CAPTURE),
    ref("phones", "Headset Earphone (Jabra Evolve)", RENDER),
    ref("cable-in", "CABLE Input (VB-Audio Virtual Cable)", RENDER),
    ref("cable-out", "CABLE Output (VB-Audio Virtual Cable)", CAPTURE),
    ref("cable-b-in", "CABLE-B Input (VB-Audio Cable B)", RENDER),
    ref("cable-b-out", "CABLE-B Output (VB-Audio Cable B)", CAPTURE),
)
INVENTORY = EndpointInventory(DEVICES)
GOOD = {MIC: "mic", CALL_MIC: "cable-in", CALL_SPEAKER: "cable-b-out", PHONES: "phones"}


def evaluate(assignments, inventory=INVENTORY, availability=READY, **kwargs):
    options = {"models_ready": True, "busy_reason": None, "running": False, **kwargs}
    return evaluate_readiness(
        assignments, inventory, call_bridge_session(), availability, **options
    )


def test_a_complete_two_cable_setup_has_no_blocking_reason() -> None:
    assert evaluate(GOOD) == ()


def test_every_applicable_reason_is_listed_not_only_the_first() -> None:
    assignments = {MIC: None, CALL_MIC: "gone", CALL_SPEAKER: "phones", PHONES: "phones"}
    reasons = evaluate(assignments, models_ready=False, busy_reason="Meeting runs", running=True)
    assert [(r.code, r.role) for r in reasons] == [
        (ReadinessCode.MISSING_ENDPOINT, MIC),
        (ReadinessCode.ENDPOINT_NOT_FOUND, CALL_MIC),
        (ReadinessCode.WRONG_FLOW, CALL_SPEAKER),
        (ReadinessCode.DUPLICATE_ENDPOINT, CALL_SPEAKER),
        (ReadinessCode.MODELS_WARMING, None),
        (ReadinessCode.SESSION_BUSY, None),
        (ReadinessCode.RUNNING, None),
    ]
    texts = [r.text for r in reasons]
    assert texts[0] == "Your microphone: select a device"
    assert texts[1] == "Call microphone cable — playback side: device not found"
    assert texts[2] == "Call speaker cable — recording side: needs a recording device"
    assert texts[3] == (
        "Call speaker cable — recording side and Your headphones use the same device"
    )
    assert texts[4:6] == ["Preparing models…", "Meeting runs"]


def test_same_virtual_cable_for_both_call_roles_is_named_with_the_install_hint() -> None:
    reasons = evaluate({**GOOD, CALL_SPEAKER: "cable-out"})
    assert [r.code for r in reasons] == [ReadinessCode.SAME_CABLE]
    assert reasons[0].text == (
        "Both call cables are the same virtual cable. "
        "Install a second cable and select it for one path."
    )


def test_ambiguous_names_and_a_missing_inventory_fail_closed() -> None:
    twin = ref("mic#2", "Headset Microphone (Jabra Evolve)", CAPTURE)
    reasons = evaluate(GOOD, inventory=EndpointInventory((*DEVICES, twin)))
    assert [(r.code, r.role) for r in reasons] == [(ReadinessCode.AMBIGUOUS_ENDPOINT, MIC)]
    assert reasons[0].text == "Your microphone: several devices have this name — unavailable"
    missing = evaluate(GOOD, inventory=None)
    assert [r.code for r in missing] == [ReadinessCode.ENDPOINT_NOT_FOUND] * 4


def test_missing_row_7_items_are_listed_one_per_line(tmp_path) -> None:
    session = call_bridge_session()
    catalog = ready_catalog(tmp_path, session, voices=(DE,))
    availability = check_call_bridge(session, catalog, GOOD)
    reasons = evaluate(GOOD, availability=availability)
    assert [r.code for r in reasons] == [ReadinessCode.MODE_UNAVAILABLE]
    assert reasons[0].text.startswith("Not available: missing voice ")
    # Endpoint requirements of row 7 are reported per role, never twice.
    unassigned = check_call_bridge(session, catalog, ())
    codes = [r.code for r in evaluate({}, availability=unassigned)]
    assert codes.count(ReadinessCode.MODE_UNAVAILABLE) == 1


def test_old_settings_with_enabled_false_keep_ids_and_do_not_gate_start() -> None:
    # AC-16: a v1 file with ``enabled: false`` and four endpoint IDs.
    legacy = {
        "call_bridge": {"enabled": False, **{f"{r.value}_endpoint_id": GOOD[r] for r in GOOD}}
    }
    config = AppConfig.from_mapping(migrate_settings(legacy))
    assert config.call_bridge.enabled is False
    assert config.call_bridge.guard_tail_ms == 300
    assignments = configured_assignments(config.call_bridge)
    assert assignments == GOOD
    assert evaluate(assignments) == ()


def test_role_labels_follow_the_path_boxes() -> None:
    assert list(ROLE_LABELS.values()) == [
        "Your microphone",
        "Call microphone cable — playback side",
        "Call speaker cable — recording side",
        "Your headphones",
    ]
