"""Settings › Audio devices → the Conversation microphone field (issue #137).

The Conversation activity row names the microphone chosen in Settings, as its combo does,
without a restart, after a device refresh and for a legacy choice migrated to unavailable;
the named device is the one a Start opens. Over the D-07 fake devices.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tests._fake_devices import CAPTURE, MICROPHONE, SPEAKERS, mic
from tests._spy_window import build_window, spies  # noqa: F401
from tests.ui._language_helpers import start
from tests.ui._notice_helpers import notice_window  # noqa: F401
from tests.ui.test_device_setup import HEADSET, settings
from tests.ui.test_main_window_session import click


def field(window) -> str:
    return window.conversation.microphone_label.text()


def test_conversation_names_the_microphone_chosen_in_settings_and_opens_it(window) -> None:
    assert field(window) == "Follow Windows default (now: Test microphone)"
    setup = settings(window)
    window.fake_devices.set(MICROPHONE, SPEAKERS, HEADSET)
    click(setup.refresh_button)
    window.input_combo.setCurrentIndex(window.input_combo.findData(HEADSET.endpoint_id))

    assert field(window) == window.input_combo.currentText() == "USB Headset"
    label = window.conversation.microphone_label
    assert label.accessibleName() == "Microphone" and label.toolTip() == "USB Headset"
    start(window)
    assert window.capture.device == HEADSET.runtime_index
    window.stop_listening()


def test_conversation_field_follows_a_refresh_and_a_new_default(window) -> None:
    setup = settings(window)
    window.fake_devices.set(MICROPHONE, HEADSET, SPEAKERS, defaults={CAPTURE: HEADSET.endpoint_id})
    click(setup.refresh_button)
    assert field(window) == "Follow Windows default (now: USB Headset)"

    window.input_combo.setCurrentIndex(window.input_combo.findData(HEADSET.endpoint_id))
    moved = mic("USB Headset", 9, "headset")  # replugged: new index, same identity
    window.fake_devices.set(MICROPHONE, moved, SPEAKERS)
    click(setup.refresh_button)
    assert field(window) == "USB Headset"
    assert setup.resolved(CAPTURE).endpoint.runtime_index == 9


def test_conversation_field_shows_a_legacy_choice_migrated_to_unavailable(
    tmp_path,
    monkeypatch,
    request,
    spies,  # noqa: F811
) -> None:
    def legacy(config, _root) -> None:
        config.audio.input_device = 7  # an index the PortAudio list no longer has

    window = build_window(tmp_path, monkeypatch, configure=legacy)
    request.addfinalizer(window.close)

    assert window.input_combo.currentText() == "Saved device — unavailable"
    assert field(window) == "Saved device — unavailable"
    assert not window.start_button.isEnabled()

    window.input_combo.setCurrentIndex(window.input_combo.findData(MICROPHONE.endpoint_id))
    assert field(window) == "Test microphone"
    assert window.start_button.isEnabled()
