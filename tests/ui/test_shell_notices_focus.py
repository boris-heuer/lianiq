"""Notice Retry, accessible names and banner focus (CAP-0168 WI-03; AC-23, AC-25, AC-26).

Split from ``test_shell_notices.py``: AC-25 **Retry** runs the Start gate; AC-26 a notice
change updates the banner's accessible name/description and never moves keyboard focus;
plus the wave-1 banner rules. The shared helpers are in ``_notice_helpers.py``.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from lianiq.ui.notices import Severity
from lianiq.ui.shell.session_owner import SessionState
from tests._spy_window import build_window, spies  # noqa: F401
from tests.ui._language_helpers import press, start, wait_until
from tests.ui._notice_helpers import (
    CONVERSATION,
    MICROPHONE,
    PAIR_SOURCE,
    SPEAKERS,
    action,
    banner,
    notice_window,  # noqa: F401
    one_turn,
    shown,
)
from tests.ui.test_main_window_accessibility import accessible_name, focused, unnamed
from tests.ui.test_main_window_session import click

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
    from tests.ui._language_helpers import only_de_to_zh_edge

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
