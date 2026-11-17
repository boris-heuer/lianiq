"""Meeting roles, endpoints, conflicts and the table partner suggestion (CAP-0177 contract §1).

Unit halves of AC-03 (*Your microphone* is the table microphone) and AC-28 (German speech on
the table speaker); both compare the endpoint IDs of the resolved endpoints.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from lianiq.meeting.contracts import (
    EndpointConflict,
    MeetingEndpoints,
    MeetingRole,
    TableInputDuringOutput,
    endpoint_conflicts,
    suggest_table_partner,
)
from tests.meeting.support import capture, render

JABRA_MIC = capture("Microphone (Jabra Speak2 75)", "jabra-in")
JABRA_SPK = render("Speakers (Jabra Speak2 75)", "jabra-out")
LAPTOP_MIC = capture("Microphone Array (Realtek(R) Audio)", "laptop-in")
LAPTOP_SPK = render("Speakers (Realtek(R) Audio)", "laptop-out")
HEADSET_SPK = render("Headphones (USB Headset)", "headset-out")


def endpoints(**overrides) -> MeetingEndpoints:
    values = {"table_capture": JABRA_MIC, "table_render": JABRA_SPK, "user_capture": LAPTOP_MIC}
    values.update(overrides)
    return MeetingEndpoints(**values)


def test_enum_values_are_the_contract_values():
    assert [role.value for role in MeetingRole] == [
        "table_capture",
        "table_render",
        "user_capture",
        "local_render",
    ]
    assert [option.value for option in TableInputDuringOutput] == ["mute", "open"]
    assert [conflict.value for conflict in EndpointConflict] == [
        "user_is_table",
        "local_is_table",
    ]


def test_endpoints_default_to_no_local_render_and_speaker_fail_safe():
    chosen = endpoints()
    assert chosen.local_render is None
    assert chosen.local_render_is_headset is False


def test_distinct_endpoints_have_no_conflict():
    assert endpoint_conflicts(endpoints(local_render=HEADSET_SPK)) == ()


def test_ac03_user_microphone_equal_to_table_microphone_is_a_conflict():
    # The resolved endpoint of a "follow Windows default" choice is compared by ID, so an
    # explicitly chosen and a default-resolved Jabra microphone conflict alike.
    same_device = capture("Microphone (Jabra Speak2 75)", "jabra-in")
    assert endpoint_conflicts(endpoints(user_capture=same_device)) == (
        EndpointConflict.USER_IS_TABLE,
    )


def test_conflicts_compare_endpoint_ids_not_display_names():
    renamed = capture("Something else entirely", "jabra-in")
    same_name = capture("Microphone (Jabra Speak2 75)", "another-id")
    assert endpoint_conflicts(endpoints(user_capture=renamed)) == (EndpointConflict.USER_IS_TABLE,)
    assert endpoint_conflicts(endpoints(user_capture=same_name)) == ()


def test_ac28_local_render_on_the_table_speaker_is_a_conflict():
    assert endpoint_conflicts(endpoints(local_render=JABRA_SPK)) == (
        EndpointConflict.LOCAL_IS_TABLE,
    )


def test_both_conflicts_are_reported_in_contract_order():
    assert endpoint_conflicts(endpoints(user_capture=JABRA_MIC, local_render=JABRA_SPK)) == (
        EndpointConflict.USER_IS_TABLE,
        EndpointConflict.LOCAL_IS_TABLE,
    )


def test_partner_is_the_other_flow_with_the_same_device_name():
    inventory = [LAPTOP_MIC, LAPTOP_SPK, JABRA_MIC, JABRA_SPK, HEADSET_SPK]
    assert suggest_table_partner(JABRA_MIC, inventory) == JABRA_SPK
    assert suggest_table_partner(JABRA_SPK, inventory) == JABRA_MIC


def test_partner_names_use_the_last_parentheses_and_the_cap0168_normalisation():
    chosen = capture("Echo Cancelling Speakerphone (Jabra  SPEAK2 75)", "jabra-in")
    partner = render("Speakers (jabra speak2 75)", "jabra-out")
    assert suggest_table_partner(chosen, [chosen, partner, LAPTOP_SPK]) == partner
    # Nested parentheses: the device name is the whole last parenthesised group.
    assert suggest_table_partner(LAPTOP_MIC, [LAPTOP_MIC, LAPTOP_SPK, JABRA_SPK]) == LAPTOP_SPK


def test_partner_falls_back_to_the_whole_name_without_parentheses():
    chosen = capture("Conference Puck", "puck-in")
    partner = render("conference  puck", "puck-out")
    assert suggest_table_partner(chosen, [chosen, partner, JABRA_SPK]) == partner


def test_partner_is_none_without_a_unique_match():
    second_jabra = render("Headset Earphone (Jabra Speak2 75)", "jabra-out-2")
    assert suggest_table_partner(JABRA_MIC, [JABRA_MIC, JABRA_SPK, second_jabra]) is None
    assert suggest_table_partner(JABRA_MIC, [JABRA_MIC, LAPTOP_SPK, HEADSET_SPK]) is None
    assert suggest_table_partner(JABRA_MIC, []) is None


def test_partner_never_returns_an_endpoint_of_the_same_flow():
    other_mic = capture("Line In (Jabra Speak2 75)", "jabra-in-2")
    assert suggest_table_partner(JABRA_MIC, [JABRA_MIC, other_mic]) is None


@pytest.mark.parametrize("name", ["Speakers ()", "( )"])
def test_partner_is_none_for_an_empty_device_name(name):
    chosen = render(name, "empty-out")
    blank = capture("Microphone ()", "empty-in")
    assert suggest_table_partner(chosen, [chosen, blank]) is None


def test_meeting_package_is_qt_free():
    script = "import sys, lianiq.meeting; print(any(m.startswith('PySide6') for m in sys.modules))"
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        check=True,
        cwd=Path(__file__).resolve().parents[2],
        text=True,
    )
    assert result.stdout.strip() == "False"
