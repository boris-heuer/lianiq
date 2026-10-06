from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from offline_translator.call_bridge.contracts import AudioEndpointRef, EndpointFlow, EndpointRole
from offline_translator.config import CallBridgeConfig
from offline_translator.ui.call_bridge_panel import CallBridgePanel


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


def test_panel_exposes_all_semantic_roles_and_returns_valid_mapping(application) -> None:
    panel = CallBridgePanel(CallBridgeConfig())
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


def test_panel_rejects_missing_assignments(application) -> None:
    panel = CallBridgePanel(CallBridgeConfig())
    panel.set_endpoints(endpoints())
    panel.enabled_checkbox.setChecked(True)

    with pytest.raises(ValueError, match="Select an endpoint"):
        panel.assignments()
