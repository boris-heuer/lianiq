"""The Call Bridge setup page (CAP-0166 WI-02): path boxes, readiness list and meters.

Offscreen widget tests over synthetic endpoints and the real ``evaluate_readiness`` with a
provisioned row-7 catalog; no audio device or model is used.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QCheckBox

from lianiq.call_bridge.contracts import AudioEndpointRef, EndpointFlow, EndpointRole, LaneId
from lianiq.call_bridge.controller import check_call_bridge
from lianiq.call_bridge.readiness import evaluate_readiness
from lianiq.config import CallBridgeConfig
from lianiq.ui import strings_call_bridge as s
from lianiq.ui.call_bridge_panel import CallBridgePanel
from tests.call_bridge.support import call_bridge_session, ready_catalog

MIC, CALL_MIC, CALL_SPEAKER, PHONES = EndpointRole
BUSY = "Stop the Conversation session first"


@pytest.fixture(scope="module")
def application():
    return QApplication.instance() or QApplication([])


def endpoints():
    return [
        AudioEndpointRef("mic", "Headset microphone (USB Headset)", EndpointFlow.CAPTURE, "W", 1),
        AudioEndpointRef("tx", "CABLE Input (VB-Audio Cable A)", EndpointFlow.RENDER, "W", 2),
        AudioEndpointRef("rx", "CABLE-B Output (VB-Audio Cable B)", EndpointFlow.CAPTURE, "W", 3),
        AudioEndpointRef("phones", "Headphones (USB Headset)", EndpointFlow.RENDER, "W", 4),
    ]


@pytest.fixture
def panel_for(application, tmp_path):
    session = call_bridge_session()
    availability = check_call_bridge(session, ready_catalog(tmp_path, session), EndpointRole)

    def readiness(assignments, inventory, **state):
        return evaluate_readiness(assignments, inventory, session, availability, **state)

    def build(config=None, checklist=None) -> CallBridgePanel:
        panel = CallBridgePanel(
            config or CallBridgeConfig(),
            local_name="German",
            remote_name="Mandarin (Simplified)",
            readiness=readiness,
            checklist=checklist,
        )
        panel.set_endpoints(endpoints())
        panel.set_models_ready(True)
        return panel

    return build


def select(panel, **overrides) -> None:
    """Select the four endpoints; ``overrides`` maps a role value to another endpoint ID."""
    for role, endpoint_id in zip(EndpointRole, ("mic", "tx", "rx", "phones"), strict=True):
        combo = panel.endpoint_combos[role]
        combo.setCurrentIndex(max(combo.findData(overrides.get(role.value, endpoint_id)), 0))


def readiness_texts(panel) -> list[str]:
    return [label.text() for label in panel.readiness_labels]


def test_ac01_the_page_has_no_enable_checkbox_and_shows_the_note_and_checklist(
    panel_for, tmp_path, monkeypatch
) -> None:
    from lianiq.ui import call_bridge_panel as module

    checklist = tmp_path / "call-bridge-operator-setup.md"
    checklist.write_text("# Checklist\n", encoding="utf-8")
    opened = []
    monkeypatch.setattr(module.QDesktopServices, "openUrl", opened.append)
    panel = panel_for(checklist=checklist)

    assert panel.findChildren(QCheckBox) == []
    assert not hasattr(panel, "enabled_checkbox") and not hasattr(panel, "state_label")
    assert panel.experimental_label.text() == s.CB_EXPERIMENTAL
    assert not panel.checklist_link.isHidden()
    assert panel.checklist_link.accessibleName() == "Real-call checklist"
    panel.open_checklist()
    assert [url.toLocalFile() for url in opened] == [checklist.as_posix()]

    assert panel_for(checklist=tmp_path / "missing.md").checklist_link.isHidden()


def test_path_boxes_name_the_session_languages_and_list_full_display_names(panel_for) -> None:
    panel = panel_for()
    outbound, inbound = panel.paths[LaneId.OUTBOUND], panel.paths[LaneId.INBOUND]

    assert outbound.title() == "You → call · German → Mandarin (Simplified)"
    assert inbound.title() == "Call → you · Mandarin (Simplified) → German"
    assert set(outbound.combos) == {MIC, CALL_MIC} and set(inbound.combos) == {CALL_SPEAKER, PHONES}
    assert {role: combo.accessibleName() for role, combo in panel.endpoint_combos.items()} == {
        MIC: "Your microphone",
        CALL_MIC: "Call microphone cable — playback side",
        CALL_SPEAKER: "Call speaker cable — recording side",
        PHONES: "Your headphones",
    }
    combo = panel.endpoint_combos[CALL_SPEAKER]
    assert [combo.itemText(i) for i in range(combo.count())] == [
        "Select a device …",
        "Headset microphone (USB Headset)",
        "CABLE-B Output (VB-Audio Cable B)",
    ]
    for box in (outbound, inbound):
        for widget in (box.level_bar, box.status_label, box.test_button, box.help_toggle):
            assert widget.accessibleName()
    assert outbound.status_label.text() == "Stopped"
    assert outbound.status_label.accessibleName() == "Lane status: Stopped"
    assert outbound.level_bar.accessibleName() == "Microphone level"
    assert inbound.level_bar.accessibleName() == "Call audio level"
    assert outbound.help_label.isHidden()
    outbound.help_toggle.click()
    assert not outbound.help_label.isHidden()
    assert outbound.help_label.text().startswith("In your call app, choose the recording side")

    panel.set_languages("Synthetic B", "Synthetic A")
    assert outbound.title() == "You → call · Synthetic B → Synthetic A"


def test_ac02_the_readiness_list_names_every_reason_and_gates_start(panel_for) -> None:
    panel = panel_for()

    assert readiness_texts(panel) == [
        "• Your microphone: select a device",
        "• Call microphone cable — playback side: select a device",
        "• Call speaker cable — recording side: select a device",
        "• Your headphones: select a device",
    ]
    assert not panel.start_button.isEnabled() and not panel.readiness_list.isHidden()

    select(panel)
    assert readiness_texts(panel) == [] and panel.readiness_list.isHidden()
    assert panel.start_button.isEnabled()

    select(panel, call_speaker_capture="mic")  # one endpoint for two roles
    assert readiness_texts(panel) == [
        "• Your microphone and Call speaker cable — recording side use the same device"
    ]
    assert not panel.start_button.isEnabled()

    select(panel)
    panel.set_models_ready(False)
    panel.set_session_busy(BUSY)
    assert readiness_texts(panel) == ["• Preparing models…", f"• {BUSY}"]
    assert panel.start_button.toolTip() == BUSY and not panel.start_button.isEnabled()

    panel.set_models_ready(True)
    panel.set_session_busy(None)
    assert panel.start_button.isEnabled() and panel.start_button.toolTip() == ""


def test_ac02_a_persisted_endpoint_that_is_gone_is_named_and_kept(panel_for) -> None:
    config = CallBridgeConfig(enabled=False, local_headphones_endpoint_id="gone")
    panel = panel_for(config)
    select(panel, local_headphones=None)  # the persisted ID is not listed

    assert "• Your headphones: device not found" in readiness_texts(panel)
    assert not panel.start_button.isEnabled()
    with pytest.raises(ValueError, match="Your headphones: device not found"):
        panel.assignments()
    panel.apply_to_config()
    assert config.local_headphones_endpoint_id == "gone" and config.enabled is False


def test_ac15_the_meter_caption_shows_signal_no_signal_and_clipping(panel_for) -> None:
    panel = panel_for()
    outbound, inbound = panel.paths[LaneId.OUTBOUND], panel.paths[LaneId.INBOUND]

    panel.set_level(MIC, 0.8)  # no stream open: the meter does not move
    assert outbound.level_bar.value() == 0 and outbound.level_caption.text() == ""
    assert not outbound.no_signal_timer.isActive()

    select(panel)
    panel.set_running(True)
    assert outbound.no_signal_timer.isActive() and outbound.no_signal_timer.interval() == 5_000
    outbound.no_signal_timer.timeout.emit()
    inbound.no_signal_timer.timeout.emit()
    assert outbound.level_caption.text() == (
        "No signal for 5 s — is the right microphone selected and unmuted?"
    )
    assert inbound.level_caption.text() == (
        "No signal for 5 s — is the call app's speaker set to the call speaker cable?"
    )
    panel.set_level(MIC, 0.6)
    assert outbound.level_caption.text() == "Signal" and outbound.level_bar.value() == 60
    assert outbound.level_caption.accessibleName() == "Microphone level: Signal"
    panel.set_clipping(CALL_SPEAKER)
    panel.set_level(CALL_SPEAKER, 0.9)  # the clipping caption is held for a moment
    assert inbound.level_caption.text() == (
        "Too loud (clipping) — lower the call app's speaker volume"
    )

    panel.set_running(False)
    assert not outbound.no_signal_timer.isActive()
    assert outbound.level_caption.text() == "" and outbound.level_bar.value() == 0
