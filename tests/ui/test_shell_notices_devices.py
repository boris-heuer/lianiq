"""Device-loss, export-failure and "+N more" notices in the shell (CAP-0168 WI-03; AC-24 UI).

Split from ``test_shell_notices.py``: device loss uses the ``DEVICE_*`` notices fed by fake
device producers over the D-07 fake devices (WI-04); the shared helpers are in
``_notice_helpers.py``.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from lianiq.ui.shell.workspaces import WorkspaceId
from tests._spy_window import spies  # noqa: F401
from tests.ui._language_helpers import start, wait_until
from tests.ui._notice_helpers import (
    CONVERSATION,
    MICROPHONE,
    SPEAKERS,
    action,
    banner,
    notice_window,  # noqa: F401
    one_turn,
    plug,
    shown,
)
from tests.ui.test_main_window_accessibility import focused
from tests.ui.test_main_window_session import click
from tests.ui.test_shell_diagnostics import ABSOLUTE_PATH


def test_ac24_playback_failure_is_speakers_lost_and_capture_continues(window, spies) -> None:  # noqa: F811
    def failing_playback(_path, _device) -> None:
        raise RuntimeError("PortAudio error -9996")

    window.pipeline.playback = failing_playback
    window.mode_combo.setCurrentText("German → Mandarin (Simplified)")
    window.tts_checkbox.setChecked(True)
    one_turn(window, spies)

    assert wait_until(lambda: banner(window).isVisible())
    title, detail, labels = shown(window)
    assert title.startswith("Action needed: Speakers 'Test speakers' disconnected.")
    assert "Recording continues. Spoken output stopped." in detail
    assert labels == ["Reconnect", "Choose device"]
    assert window.capture.running and window.target_text.toPlainText().strip()
    assert window.pipeline.voice_output is False
    reconnect = action(window, "Reconnect")
    assert not reconnect.isEnabled() and reconnect.toolTip() == "Available after Stop"

    window.stop_listening()
    assert reconnect.isEnabled() and reconnect.toolTip() == ""
    click(reconnect)  # the speakers are still enumerated: resolved
    assert window.notices.live() == ()


def test_ac24_microphone_lost_stops_the_session_and_reconnect_restores_start(
    window,
    spies,  # noqa: F811
    monkeypatch,
) -> None:
    one_turn(window, spies)
    plug(monkeypatch, SPEAKERS)  # the headset is unplugged
    window.conversation.notices.microphone_lost("USB Headset")

    assert not window.capture.running and window.session_owner.state.value == "idle"
    assert len(window.history) == 1 and "Guten Tag" in window.source_text.toPlainText()
    title, detail, labels = shown(window)
    assert title == (
        "Action needed: Microphone 'USB Headset' disconnected. Recording stopped. "
        "Your transcript is kept."
    )
    assert "Recording stopped. Playback stopped." in detail
    assert labels == ["Reconnect", "Choose device"]

    click(action(window, "Reconnect"))  # still unplugged: the same notice again
    assert window.notices.count(CONVERSATION) == 1
    assert window.notices.top(CONVERSATION).repeats == 1
    assert not window.capture.running  # nothing restarts on its own

    plug(monkeypatch, MICROPHONE, SPEAKERS)  # replugged
    click(action(window, "Reconnect"))
    # Only the Settings info that the Windows default microphone is back stays (AC-16).
    assert window.notices.live(CONVERSATION) == ()
    assert window.start_button.isEnabled()
    start(window)  # the user's Start works again
    assert len(window.history) == 1


def test_ac24_choose_device_focuses_the_device_selector(window) -> None:
    window.show_workspace(WorkspaceId.SETTINGS)
    window.conversation.notices.speakers_lost("Desk speakers")
    window.show_workspace(CONVERSATION)
    click(action(window, "Choose device"))
    # The selectors are in Settings › Audio devices (spec §2.3.5, WI-04).
    assert window.current_workspace() is WorkspaceId.SETTINGS
    assert wait_until(lambda: focused() is window.output_combo)


def test_ac24_transcript_export_failure_keeps_history_and_offers_retry(
    window,
    spies,  # noqa: F811
    monkeypatch,
    tmp_path,
) -> None:
    from PySide6.QtWidgets import QFileDialog, QPushButton

    one_turn(window, spies)
    window.stop_listening()
    target = tmp_path / "missing-folder" / "t.txt"
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", staticmethod(lambda *_a: (str(target), "Text (*.txt)"))
    )
    export = next(b for b in window.findChildren(QPushButton) if b.text() == "Export transcript")
    click(export)

    title, _detail, labels = shown(window)
    assert title.startswith("Warning: Export failed: ") and title.endswith("try another folder.")
    assert labels == ["Retry"]
    # The reason is redacted: no absolute path, not even the folder names (wave-1 B5).
    assert not ABSOLUTE_PATH.search(title), title
    assert "missing-folder" not in title and tmp_path.name not in title
    assert "saved" not in window.statusBar().currentMessage().lower()
    assert len(window.history) == 1

    target.parent.mkdir()
    click(action(window, "Retry"))
    assert target.exists() and window.notices.live() == ()
    assert window.statusBar().currentMessage() == f"Transcript saved: {target}"


def test_more_opens_diagnostics_with_the_notice_history(window) -> None:
    window.show_error("First failure")
    window.devices = [SPEAKERS]
    window.start_listening()
    more = banner(window).more_button
    assert more.isVisible() and more.text() == "+1 more"

    click(more)

    assert window.current_workspace() is WorkspaceId.SETTINGS
    history = window.settings.diagnostics_view.history_text.toPlainText()
    assert "conversation.error: First failure" in history
    assert "conversation.unavailable: Not available: missing microphone" in history
