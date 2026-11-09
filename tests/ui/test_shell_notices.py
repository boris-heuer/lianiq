"""Notices in the shell (CAP-0168 WI-03; spec §2.3.4, §2.2.3, §2.2.5): offscreen UI tests.

AC-24 (UI): each mapped Conversation failure shows exactly one notice in the workspace
banner naming what failed, the mode/language, whether recording/playback continues and its
action. AC-25: **Retry** runs the Start gate. AC-26: a notice change updates the banner's
accessible name/description and never moves keyboard focus. Device loss uses the
``DEVICE_*`` notices fed by fake device producers (WI-04 wires the real detection).
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from lianiq.audio.devices import AudioDevice
from lianiq.pipeline import PipelineEvent, PipelineEventKind
from lianiq.ui.notices import Severity
from lianiq.ui.shell.session_owner import SessionState
from lianiq.ui.shell.workspaces import WorkspaceId
from tests.test_requirement_scoped_loading import build_window, spies  # noqa: F401
from tests.ui.test_main_window_accessibility import accessible_name, focused, unnamed
from tests.ui.test_main_window_languages import press, start, submit, transcript, wait_until
from tests.ui.test_main_window_session import click
from tests.ui.test_shell_diagnostics import ABSOLUTE_PATH

CONVERSATION = WorkspaceId.CONVERSATION
MICROPHONE = AudioDevice(0, "Test microphone", 1, 0)
SPEAKERS = AudioDevice(1, "Test speakers", 0, 2)
PAIR_SOURCE = "Conversation · German ↔ Mandarin (Simplified)"


@pytest.fixture
def window(tmp_path, spies, monkeypatch):  # noqa: F811
    window = build_window(tmp_path, monkeypatch)
    window.activateWindow()
    yield window
    window.stop_listening()
    window.close()


def plug(monkeypatch, *devices) -> None:
    """The fake device inventory the next enumeration (Reconnect) reads."""
    import lianiq.ui.workspaces.conversation as conversation_module

    monkeypatch.setattr(conversation_module, "list_audio_devices", lambda: list(devices))


def banner(window, workspace=CONVERSATION):
    return window.banners[workspace]


def shown(window, workspace=CONVERSATION):
    """(title, detail, action labels) of the visible banner."""
    item = banner(window, workspace)
    assert item.isVisible()
    labels = [button.accessibleName() for button in item.action_buttons]
    return item.title_label.text(), item.detail_label.text(), labels


def action(window, label: str, workspace=CONVERSATION):
    return next(b for b in banner(window, workspace).action_buttons if b.accessibleName() == label)


def one_turn(window, spies) -> None:  # noqa: F811
    start(window)
    submit(window, spies, transcript("Guten Tag", "de"))
    assert wait_until(lambda: len(window.history) == 1)


# AC-24 (UI) -------------------------------------------------------------------------------


def test_no_notice_no_banner(window) -> None:
    assert window.notices.live() == ()
    assert not banner(window).isVisible()


def test_ac24_mode_unavailable_is_one_blocking_notice_with_retry(window) -> None:
    window.devices = [SPEAKERS]  # no microphone enumerated
    window.start_listening()

    title, detail, labels = shown(window)
    assert title == "Action needed: Not available: missing microphone"
    assert detail.startswith(PAIR_SOURCE + ". Recording has not started.")
    assert labels == ["Retry"]
    assert window.notices.count(CONVERSATION) == 1
    assert not window.capture.running


def test_ac24_model_failure_is_one_blocking_notice(window, spies) -> None:  # noqa: F811
    spies.failing_warm_up_calls = {1}
    click(window.start_button)
    assert wait_until(lambda: window.state_label.text() == "Model error")

    title, detail, labels = shown(window)
    assert title == "Action needed: Models could not be prepared: warm-up 1 failed"
    assert "Recording has not started." in detail and labels == ["Retry"]
    assert window.notices.count(CONVERSATION) == 1


def test_ac24_pair_locked_is_an_info_notice_cleared_by_stop(window) -> None:
    start(window)
    window.conversation._selection_changed()  # a selection change reaches the locked gate

    title, detail, labels = shown(window)
    assert title == "Information: Stop the session to change language pair or mode"
    assert "Recording continues." in detail and "Press Stop (F9) first." in detail
    assert labels == []
    window.stop_listening()
    assert window.notices.live() == () and not banner(window).isVisible()


def test_ac24_held_turns_discarded_on_stop_is_a_warning(window, spies) -> None:  # noqa: F811
    start(window)
    submit(window, spies, transcript("It is a test.", "en"))
    assert wait_until(window.held_turn_bar.isVisible)
    assert not banner(window).isVisible()  # the held-turn bar stays primary while running

    click(window.stop_button)

    title, detail, labels = shown(window)
    assert title == "Warning: 1 turn(s) with an unclear language were discarded"
    assert "Recording stopped. Your transcript is kept." in detail
    assert "No action needed" in detail and labels == []
    assert banner(window).dismiss_button.isVisible()
    click(banner(window).dismiss_button)
    assert not banner(window).isVisible() and window.notices.live() == ()


@pytest.mark.parametrize(
    ("event", "expected", "continues"),
    [
        (
            PipelineEvent(PipelineEventKind.QUEUE_OVERFLOW),
            "Warning: The audio queue was full; the oldest pending segment was dropped.",
            "Recording continues.",
        ),
        (
            PipelineEvent(PipelineEventKind.TURNS_DROPPED, count=2),
            (
                "Warning: 2 queued speech segment(s) were not translated before the session "
                "stopped and were dropped."
            ),
            "Recording stopped.",
        ),
    ],
)
def test_ac24_pipeline_overflow_and_dropped_turns_are_notices(window, event, expected, continues):
    start(window)
    window.runner.on_event(event)  # what the pipeline worker reports
    window.runner.on_event(event)  # a repeat updates the one notice

    title, detail, labels = shown(window)
    assert title == f"{expected} (2×)"
    assert continues in detail and "Conversation" in detail and labels == []
    assert window.notices.count(CONVERSATION) == 1


def test_ac24_a_pipeline_event_of_an_older_session_is_dropped(window) -> None:
    start(window)
    old = window.session_owner.generation
    window.stop_listening()
    start(window)
    window.bridge.pipeline_event.emit(PipelineEvent(PipelineEventKind.QUEUE_OVERFLOW), old)
    assert window.notices.live() == ()
    window.bridge.pipeline_event.emit(
        PipelineEvent(PipelineEventKind.QUEUE_OVERFLOW), window.session_owner.generation
    )
    assert window.notices.count(CONVERSATION) == 1


def test_ac24_missing_voice_is_a_warning_with_text_only_output(tmp_path, spies, monkeypatch):  # noqa: F811
    from tests.ui.test_main_window_languages import without_mandarin_voice

    window = build_window(tmp_path, monkeypatch, configure=without_mandarin_voice)
    try:
        title, detail, labels = shown(window)
        assert title == "Warning: Not available: missing voice Mandarin (Simplified)"
        assert "translations appear as text only" in detail and labels == []
        window.mode_combo.setCurrentText("Mandarin (Simplified) → German")  # German voice exists
        assert window.notices.live() == () and not banner(window).isVisible()
    finally:
        window.close()


def test_ac24_playback_failure_is_speakers_lost_and_capture_continues(window, spies) -> None:  # noqa: F811
    def failing_playback(_path, _device) -> None:
        raise RuntimeError("PortAudio error -9996")

    window.pipeline.playback = failing_playback
    window.mode_combo.setCurrentText("German → Mandarin (Simplified)")
    window.tts_checkbox.setChecked(True)
    one_turn(window, spies)

    assert wait_until(lambda: banner(window).isVisible())
    title, detail, labels = shown(window)
    assert title.startswith("Action needed: Speakers 'Windows default' disconnected.")
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
    assert window.notices.live() == ()
    assert window.start_button.isEnabled()
    start(window)  # the user's Start works again
    assert len(window.history) == 1


def test_ac24_choose_device_focuses_the_device_selector(window) -> None:
    window.show_workspace(WorkspaceId.SETTINGS)
    window.conversation.notices.speakers_lost("Desk speakers")
    window.show_workspace(CONVERSATION)
    click(action(window, "Choose device"))
    assert window.current_workspace() is CONVERSATION
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


# AC-25 ------------------------------------------------------------------------------------


def test_ac25_retry_runs_the_start_gate_and_keeps_completed_turns(window, spies) -> None:  # noqa: F811
    one_turn(window, spies)
    window.stop_listening()
    window.devices = [SPEAKERS]  # the prerequisite is missing
    window.start_listening()
    retry = action(window, "Retry")

    from PySide6.QtCore import Qt

    retry.setFocus()
    assert wait_until(lambda: focused() is retry)
    press(retry, Qt.Key.Key_Space)  # keyboard: the same gate fails with the same notice

    assert window.notices.count(CONVERSATION) == 1
    assert shown(window)[0] == "Action needed: Not available: missing microphone (2×)"
    assert focused() is retry  # the repeated notice kept the focused button
    assert not window.capture.running and not window.conversation.starting
    assert len(window.history) == 1

    window.devices = [MICROPHONE, SPEAKERS]  # the prerequisite is back
    generation = window.session_owner.generation
    click(retry)
    assert wait_until(lambda: window.capture.running)  # Retry started the session
    # Through the owner's Start gate: a new generation that reached RUNNING.
    assert window.session_owner.state is SessionState.RUNNING
    assert window.session_owner.active is CONVERSATION
    assert window.session_owner.generation == generation + 1
    assert window.notices.live() == () and not banner(window).isVisible()
    assert len(window.history) == 1


def test_ac25_retry_after_a_model_failure_starts_when_the_models_load(window, spies) -> None:  # noqa: F811
    spies.failing_warm_up_calls = {1}
    click(window.start_button)
    assert wait_until(lambda: window.state_label.text() == "Model error")

    click(action(window, "Retry"))

    assert wait_until(lambda: window.capture.running)
    assert window.notices.live() == ()


# AC-26 ------------------------------------------------------------------------------------


def test_ac26_a_notice_change_updates_the_banner_name_without_moving_focus(window) -> None:
    from PySide6.QtGui import QAccessible

    window.source_text.setFocus()
    assert wait_until(lambda: focused() is window.source_text)
    interface = QAccessible.queryAccessibleInterface(banner(window))

    window.show_error("Translation failed: model crashed")
    assert interface.text(QAccessible.Text.Name) == "Warning: Translation failed: model crashed"
    assert interface.text(QAccessible.Text.Description).startswith(PAIR_SOURCE + ".")
    assert focused() is window.source_text

    window.devices = [SPEAKERS]
    window.start_listening()  # a blocking notice becomes the top one
    assert accessible_name(banner(window)).startswith("Action needed: Not available")
    assert focused() is window.source_text

    window.resolve_notices([n.key for n in window.notices.live()])
    assert not banner(window).isVisible()
    assert accessible_name(banner(window)) == "Notices"
    assert focused() is window.source_text


def test_ac26_a_resolved_notice_with_a_focused_button_parks_focus_on_the_banner(window) -> None:
    window.devices = [SPEAKERS]
    window.start_listening()
    retry = action(window, "Retry")
    retry.setFocus()
    assert wait_until(lambda: focused() is retry)

    window.show_error("Another failure")  # lower severity: the blocking notice stays on top
    assert focused() is retry
    window.notices.resolve(window.notices.top(CONVERSATION).key)  # now the warning is on top

    assert banner(window).isVisible() and focused() is banner(window)


def test_ac26_uia_banner_and_its_buttons_are_named_tab_stops(window) -> None:
    """The UI Automation view (Qt accessibility interface): no unnamed Tab stop appears."""
    from PySide6.QtGui import QAccessible

    window.show_error("First failure")
    window.devices = [SPEAKERS]
    window.start_listening()
    assert unnamed(window) == []
    names = [accessible_name(b) for b in banner(window).action_buttons]
    assert names == ["Retry"]
    assert accessible_name(banner(window).more_button) == "+1 more"
    interface = QAccessible.queryAccessibleInterface(banner(window))
    assert interface.text(QAccessible.Text.Name).startswith("Action needed: ")
    assert "Recording has not started." in interface.text(QAccessible.Text.Description)
    assert window.notices.top(CONVERSATION).severity is Severity.BLOCKING


# AC-23 at banner level (wave-1 B3) --------------------------------------------------------


def test_ac23_a_blocking_notice_has_no_dismiss_and_cannot_be_dismissed(window) -> None:
    window.devices = [SPEAKERS]
    window.start_listening()
    item = banner(window)
    assert window.notices.top(CONVERSATION).severity is Severity.BLOCKING
    assert item.dismiss_button.isHidden()

    item.dismiss_button.click()  # even a programmatic click leaves it live
    item._dismiss()
    assert window.notices.count(CONVERSATION) == 1
    assert shown(window)[0] == "Action needed: Not available: missing microphone"

    window.show_error("A warning")  # still below the blocking notice: no Dismiss
    assert item.dismiss_button.isHidden()
    window.notices.resolve(window.notices.top(CONVERSATION).key)
    assert not item.dismiss_button.isHidden()  # the warning on top can be dismissed


# Focus when the banner changes (wave-1 A2) ------------------------------------------------


@pytest.mark.parametrize("control", ["dismiss", "action"])
def test_focus_in_a_banner_that_hides_goes_to_the_workspace_entry(window, control) -> None:
    from PySide6.QtCore import Qt

    if control == "dismiss":
        window.show_error("A warning")
        target = banner(window).dismiss_button
    else:
        window.conversation.notices.speakers_lost("Desk speakers")
        target = action(window, "Choose device")
    target.setFocus()
    assert wait_until(lambda: window.focusWidget() is target)

    if control == "dismiss":
        press(target, Qt.Key.Key_Space)  # keyboard Dismiss of the last notice
    else:
        window.notices.resolve(window.notices.top(CONVERSATION).key)

    assert not banner(window).isVisible()
    assert window.focusWidget() is window.navigation.buttons[CONVERSATION]


def test_focus_on_a_hidden_dismiss_or_more_parks_on_the_banner(window) -> None:
    window.show_error("A warning")
    dismiss = banner(window).dismiss_button
    dismiss.setFocus()
    assert wait_until(lambda: window.focusWidget() is dismiss)
    window.devices = [SPEAKERS]
    window.start_listening()  # a blocking notice on top hides Dismiss
    assert dismiss.isHidden() and window.focusWidget() is banner(window)

    more = banner(window).more_button
    more.setFocus()
    assert wait_until(lambda: window.focusWidget() is more)
    window.notices.resolve("conversation.error")  # no other notice: "+N more" hides
    assert more.isHidden() and window.focusWidget() is banner(window)


# Literal ampersands (wave-1 A7) -----------------------------------------------------------


def test_button_text_escapes_ampersands_for_a_literal_label(window) -> None:
    from lianiq.ui import notice_catalog as catalog
    from lianiq.ui.notice_banner import button_text
    from lianiq.ui.notices import NoticeAction

    assert button_text("Listen & translate") == "Listen && translate"
    assert button_text("A && B") == "A &&&& B"
    assert button_text("Retry") == "Retry"
    from dataclasses import replace

    notice = catalog.error(CONVERSATION, "Export & share failed")
    window.post_notice(replace(notice, actions=(NoticeAction("Save & retry", lambda: None),)))
    button = action(window, "Save & retry")
    assert button.text() == "Save && retry"  # shown as "Save & retry", no mnemonic


# Switch direction refused (wave-1 A6) -----------------------------------------------------


def test_a_refused_direction_switch_is_an_info_notice(tmp_path, spies, monkeypatch) -> None:  # noqa: F811
    from tests.ui.test_main_window_languages import only_de_to_zh_edge

    window = build_window(tmp_path, monkeypatch, configure=only_de_to_zh_edge)
    try:
        click(window.swap_button)  # Automatic -> the available German → Mandarin
        assert window.notices.live() == ()
        click(window.swap_button)  # the reverse direction is unavailable

        title, detail, labels = shown(window)
        assert title == (
            "Information: Not available: missing translation Mandarin (Simplified) → German"
        )
        assert "The direction is unchanged." in detail and labels == []
        assert window.mode_combo.currentText() == "German → Mandarin (Simplified)"
        start(window)  # a running session resolves it
        assert window.notices.live() == ()
        window.stop_listening()
    finally:
        window.close()
