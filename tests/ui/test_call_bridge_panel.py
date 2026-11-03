from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from lianiq.call_bridge.contracts import AudioEndpointRef, EndpointFlow, EndpointRole
from lianiq.config import CallBridgeConfig
from lianiq.ui.call_bridge_panel import CallBridgePanel


@pytest.fixture(scope="module")
def application():
    return QApplication.instance() or QApplication([])


def endpoints():
    return [
        AudioEndpointRef("mic", "Headset microphone", EndpointFlow.CAPTURE, "WASAPI", 1),
        AudioEndpointRef("tx", "TX cable", EndpointFlow.RENDER, "WASAPI", 2),
        AudioEndpointRef("rx", "RX cable", EndpointFlow.CAPTURE, "WASAPI", 3),
        AudioEndpointRef("phones", "Headphones", EndpointFlow.RENDER, "WASAPI", 4),
    ]


def panel_for(local: str = "German", remote: str = "Mandarin (Simplified)") -> CallBridgePanel:
    return CallBridgePanel(CallBridgeConfig(), local_name=local, remote_name=remote)


def test_panel_exposes_all_semantic_roles_and_returns_valid_mapping(application) -> None:
    panel = panel_for()
    panel.set_endpoints(endpoints())
    panel.enabled_checkbox.setChecked(True)
    for role, endpoint_id in {
        EndpointRole.LOCAL_MICROPHONE: "mic",
        EndpointRole.CALL_MICROPHONE_RENDER: "tx",
        EndpointRole.CALL_SPEAKER_CAPTURE: "rx",
        EndpointRole.LOCAL_HEADPHONES: "phones",
    }.items():
        combo = panel.endpoint_combos[role]
        combo.setCurrentIndex(combo.findData(endpoint_id))

    assert set(panel.assignments()) == set(EndpointRole)
    assert panel.assigned_roles() == frozenset(EndpointRole)


def test_panel_rejects_missing_assignments(application) -> None:
    panel = panel_for()
    panel.set_endpoints(endpoints())
    panel.enabled_checkbox.setChecked(True)

    with pytest.raises(ValueError, match="Select an endpoint for Local microphone · German source"):
        panel.assignments()
    assert panel.assigned_roles() == frozenset()


def test_role_labels_and_test_buttons_come_from_the_pair_and_local_language(application) -> None:
    panel = panel_for()

    assert {role: label.text() for role, label in panel.role_label_widgets.items()} == {
        EndpointRole.LOCAL_MICROPHONE: "Local microphone · German source",
        EndpointRole.CALL_MICROPHONE_RENDER: "Call microphone output · Mandarin (Simplified) to call",
        EndpointRole.CALL_SPEAKER_CAPTURE: "Call speaker input · Mandarin (Simplified) from call",
        EndpointRole.LOCAL_HEADPHONES: "Local headphones · German playback",
    }
    assert panel.outbound_test_button.text() == "Test Mandarin (Simplified) → call mic"
    assert panel.inbound_test_button.text() == "Test German → headphones"
    assert (
        panel.endpoint_combos[EndpointRole.LOCAL_HEADPHONES].accessibleName()
        == "Local headphones · German playback"
    )

    panel.set_languages("Synthetic B", "Synthetic A")

    assert (
        panel.role_label_widgets[EndpointRole.LOCAL_MICROPHONE].text()
        == "Local microphone · Synthetic B source"
    )
    assert panel.outbound_test_button.text() == "Test Synthetic A → call mic"
    assert panel.inbound_test_button.text() == "Test Synthetic B → headphones"
