"""Settings › Audio devices lists and choices (CAP-0168 WI-04; AC-13..AC-17 UI, E-11).

Over the D-07 fake devices (``window.fake_devices``); loss, the monitor and the device
tests are in ``test_device_loss.py`` and ``test_device_tests.py``.
"""

from __future__ import annotations

import os
import re

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from lianiq.ui import notice_catalog as catalog
from lianiq.ui.shell.workspaces import WorkspaceId
from tests._fake_devices import CAPTURE, MICROPHONE, SPEAKERS, mic, unusable
from tests._spy_window import build_window, spies  # noqa: F401
from tests.ui._language_helpers import items
from tests.ui._notice_helpers import notice_window  # noqa: F401
from tests.ui.test_main_window_session import click

HEADSET = mic("USB Headset", 3, "headset")
ENDPOINT_ID = re.compile(r"windows-mmdevice:|audio-endpoint:|\{0\.0\.")
MIC_KEY = catalog.device_unavailable_key("Microphone")


def saved_headset(config, _root) -> None:
    config.audio.input_policy = "explicit"
    config.audio.input_endpoint_id = HEADSET.endpoint_id
    config.audio.input_device_name = "USB Headset"


def settings(window):
    window.show_workspace(WorkspaceId.SETTINGS)
    return window.device_setup


def texts(combo) -> list[str]:
    from PySide6.QtCore import Qt

    values = [combo.toolTip(), combo.accessibleName(), combo.accessibleDescription()]
    for index in range(combo.count()):
        values += [combo.itemText(index), str(combo.itemData(index, Qt.ItemDataRole.ToolTipRole))]
    return values


def test_ac13_refresh_while_stopped_updates_lists_and_keeps_the_identity(window) -> None:
    setup = settings(window)
    window.fake_devices.set(MICROPHONE, SPEAKERS, HEADSET)
    click(setup.refresh_button)
    window.input_combo.setCurrentIndex(window.input_combo.findData(HEADSET.endpoint_id))
    assert window.config.audio.input_endpoint_id == HEADSET.endpoint_id

    moved = mic("USB Headset", 9, "headset")  # replugged: new index, same identity
    window.fake_devices.set(moved, mic("Webcam", 2, "cam"), SPEAKERS)
    click(setup.refresh_button)

    assert window.fake_devices.reinitialized == 2
    assert items(window.input_combo) == [
        "Follow Windows default (now: USB Headset)",
        "USB Headset",
        "Webcam",
    ]
    assert window.input_combo.currentText() == "USB Headset"
    assert setup.resolved(CAPTURE).endpoint.runtime_index == 9


def test_ac14_missing_saved_device_is_unavailable_and_start_is_refused(
    tmp_path,
    monkeypatch,
    request,
    spies,  # noqa: F811
) -> None:
    window = build_window(tmp_path, monkeypatch, configure=saved_headset)
    request.addfinalizer(window.close)

    assert window.input_combo.currentText() == "USB Headset — unavailable"
    model = window.input_combo.model()
    assert not model.item(window.input_combo.currentIndex()).isEnabled()
    notice = window.notices.get(MIC_KEY)
    assert notice.title == "USB Headset — unavailable"
    assert [action.label for action in notice.actions] == ["Choose device"]
    assert not window.start_button.isEnabled()

    window.start_listening()  # F8: refused again, nothing opened
    assert not window.capture.running and window.session_owner.state.value == "idle"
    assert window.notices.get(MIC_KEY).repeats == 1
    assert window.config.audio.input_endpoint_id == HEADSET.endpoint_id  # nothing replaced

    window.input_combo.setCurrentIndex(0)  # the user chooses Follow Windows default
    assert window.notices.get(MIC_KEY) is None and window.start_button.isEnabled()
    assert "USB Headset — unavailable" not in items(window.input_combo)


def test_ac15_duplicate_names_are_numbered_and_no_text_shows_an_endpoint_id(window) -> None:
    from lianiq.call_bridge.contracts import AudioEndpointRef

    twins = [
        AudioEndpointRef(f"audio-endpoint:v1:capture:abc#{n}", "Headset", CAPTURE, "WASAPI", n)
        for n in (4, 5)
    ]
    setup = settings(window)
    window.fake_devices.set(*twins, SPEAKERS)
    click(setup.refresh_button)
    window.input_combo.setCurrentIndex(2)

    assert items(window.input_combo)[1:] == ["Headset", "Headset (2)"]
    assert setup.resolved(CAPTURE).endpoint.runtime_index == 5
    for combo in (window.input_combo, window.output_combo):
        leaked = [text for text in texts(combo) if ENDPOINT_ID.search(text)]
        assert leaked == []
    assert "Headset · WASAPI · 1 channel(s)" in window.input_combo.toolTip()


def test_ac16_follow_default_names_the_default_and_refresh_reports_a_new_one(window) -> None:
    setup = settings(window)
    assert window.input_combo.currentText() == "Follow Windows default (now: Test microphone)"
    window.fake_devices.set(MICROPHONE, HEADSET, SPEAKERS, defaults={CAPTURE: HEADSET.endpoint_id})
    click(setup.refresh_button)

    assert window.input_combo.currentText() == "Follow Windows default (now: USB Headset)"
    notice = window.notices.get("device.microphone-default")
    assert notice.title == "Windows default microphone is now 'USB Headset'"
    assert notice.severity.name == "INFO" and notice.workspace is WorkspaceId.SETTINGS
    assert setup.resolved(CAPTURE).endpoint == HEADSET
    # The Call Bridge selectors never offer the Windows default (fail-closed).
    for combo in window.call_bridge_panel.endpoint_combos.values():
        assert not any(text.startswith("Follow Windows default") for text in items(combo))


@pytest.mark.parametrize("explicit", [False, True], ids=["listed", "saved"])
def test_ac17_unusable_endpoint_is_listed_disabled_and_cannot_be_started(
    window,
    explicit,
) -> None:
    dock = unusable("Line In (Dock)", CAPTURE, 6, "dock")
    setup = settings(window)
    window.fake_devices.set(MICROPHONE, dock, SPEAKERS)
    click(setup.refresh_button)
    index = window.input_combo.findData(dock.endpoint_id)
    reason = "Line In (Dock) — This device has no usable input channels"
    assert window.input_combo.itemText(index) == reason
    assert not window.input_combo.model().item(index).isEnabled()
    if not explicit:
        return
    window.input_combo.setCurrentIndex(index)  # e.g. saved before the dock lost its input

    assert window.notices.get(MIC_KEY).title == reason
    window.start_listening()
    assert not window.capture.running


def test_e11_legacy_index_migrates_with_an_info_notice(
    tmp_path,
    monkeypatch,
    request,
    spies,  # noqa: F811
) -> None:
    def legacy(config, _root) -> None:
        config.audio.input_device = 0  # "Test microphone" in the full PortAudio list

    window = build_window(tmp_path, monkeypatch, configure=legacy)
    request.addfinalizer(window.close)

    assert window.input_combo.currentText() == "Test microphone"
    notice = window.notices.get("device.microphone-migrated")
    assert notice.title == "Microphone set to 'Test microphone' from your previous settings"
    audio = window.config.audio
    assert audio.input_device is None and audio.input_policy == "explicit"
    assert audio.input_endpoint_id == MICROPHONE.endpoint_id
    assert audio.output_policy == "follow_default" and audio.output_device is None
