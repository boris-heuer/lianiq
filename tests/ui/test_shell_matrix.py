"""AC-33 (UI): one automated test per shell-side matrix row (CAP-0168 WI-05).

Rows: pair change while stopped, unsupported pair, missing voice, disconnected device,
export failure, keyboard-only. Each runs in the styled shell and checks what the user sees:
the workspace banner shows the notice with its actions in full (none cut at 850×560), and
Start/Stop stay reachable. The row-specific behaviour is also covered in depth by the
WI-02..WI-04 tests named in each docstring.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from lianiq.ui import theme
from lianiq.ui.shell.workspaces import WorkspaceId
from tests._fake_devices import MICROPHONE
from tests._spy_window import build_window, spies  # noqa: F401
from tests.ui._language_helpers import (
    DE,
    DE_TO_ZH,
    PLANNED,
    ZH_TO_DE,
    only_de_to_zh_edge,
    start,
    submit,
    transcript,
    wait_until,
    without_mandarin_voice,
)
from tests.ui._layout_checks import elided, in_view, load_ui_fonts, settle
from tests.ui._navigation_helpers import activate, press
from tests.ui._notice_helpers import shown
from tests.ui.test_main_window_accessibility import focused
from tests.ui.test_main_window_session import click

CONVERSATION = WorkspaceId.CONVERSATION


def styled(tmp_path, monkeypatch, request, **options):
    load_ui_fonts()
    window = build_window(tmp_path, monkeypatch, **options)
    theme.apply(window, high_contrast=False)
    activate(window)
    settle(window, 850, 560)
    request.addfinalizer(window.close)
    request.addfinalizer(window.stop_listening)
    return window


def test_ac33_pair_change_while_stopped(tmp_path, spies, monkeypatch, request) -> None:  # noqa: F811
    """Stop → change the direction → Start uses it (also ``test_ac13_*`` in languages)."""
    from PySide6.QtCore import Qt

    window = styled(tmp_path, monkeypatch, request)
    start(window)
    assert not window.mode_combo.isEnabled()
    press(window, Qt.Key.Key_F9)
    assert wait_until(lambda: window.mode_combo.isEnabled())
    window.mode_combo.setFocus()
    while window.mode_combo.currentText() != DE_TO_ZH:
        press(window.mode_combo, Qt.Key.Key_Down)
    start(window)
    assert window.session_controller.session.fixed_source == DE
    assert elided(window) == []


def test_ac33_unsupported_pair(tmp_path, spies, monkeypatch, request) -> None:  # noqa: F811
    """Planned entries cannot be chosen; the missing direction is a notice (``test_ac03_*``)."""
    from PySide6.QtCore import Qt

    window = styled(tmp_path, monkeypatch, request, configure=only_de_to_zh_edge)
    window.pair_combo.setFocus()
    for key in (Qt.Key.Key_Down, Qt.Key.Key_End):
        press(window.pair_combo, key)
    assert window.pair_combo.currentIndex() == 0 and PLANNED[0] in window.pair_combo.itemText(1)
    click(window.swap_button)  # Automatic → the available fixed direction
    click(window.swap_button)  # the reverse direction is unavailable: an info notice
    title, _detail, _labels = shown(window)
    assert ZH_TO_DE in title or "missing translation" in title
    assert window.mode_combo.currentText() == DE_TO_ZH
    assert elided(window) == [] and in_view(window.start_button, window)


def test_ac33_missing_voice(tmp_path, spies, monkeypatch, request) -> None:  # noqa: F811
    """Text-only output with a warning (also ``test_ac24_missing_voice_*``)."""
    window = styled(tmp_path, monkeypatch, request, configure=without_mandarin_voice)
    title, detail, _labels = shown(window)
    assert title == "Warning: Not available: missing voice Mandarin (Simplified)"
    assert "text only" in detail
    assert not window.tts_checkbox.isEnabled() and window.start_button.isEnabled()
    assert elided(window) == []


def test_ac33_disconnected_device(tmp_path, spies, monkeypatch, request) -> None:  # noqa: F811
    """Microphone unplugged: blocking notice, Choose device opens Settings (``test_ac19_*``)."""
    window = styled(tmp_path, monkeypatch, request)
    start(window)
    window.fake_devices.unplug(MICROPHONE)
    window.device_setup.monitor_tick()
    title, _detail, labels = shown(window)
    assert "disconnected" in title and labels == ["Reconnect", "Choose device"]
    assert elided(window) == []
    choose = window.banners[CONVERSATION].action_buttons[1]
    click(choose)
    assert window.current_workspace() is WorkspaceId.SETTINGS
    assert elided(window) == []


def test_ac33_export_failure(tmp_path, spies, monkeypatch, request) -> None:  # noqa: F811
    """A failed transcript export: warning with Retry, focus back on the button."""
    from PySide6.QtWidgets import QFileDialog

    window = styled(tmp_path, monkeypatch, request)
    start(window)
    submit(window, spies, transcript("Guten Tag", "de"))
    assert wait_until(lambda: len(window.history) == 1)
    target = tmp_path / "missing-folder" / "transcript.txt"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *_a: (str(target), "")))
    button = window.conversation.export_button
    click(button)
    title, _detail, labels = shown(window)
    assert title.startswith("Warning: Export failed: ") and labels == ["Retry"]
    assert focused() is button and not target.exists()
    assert elided(window) == []


def test_ac33_keyboard_only(tmp_path, spies, monkeypatch, request) -> None:  # noqa: F811
    """Start, Stop and navigation by keyboard alone (also ``test_presentation_focus.py``)."""
    from PySide6.QtCore import Qt

    window = styled(tmp_path, monkeypatch, request)
    window.navigation.buttons[CONVERSATION].setFocus()
    while focused() is not window.start_button:
        press(focused(), Qt.Key.Key_Tab)
    press(window.start_button, Qt.Key.Key_Space)
    assert wait_until(lambda: window.capture.running)
    press(focused(), Qt.Key.Key_6, Qt.KeyboardModifier.ControlModifier)
    assert window.current_workspace() is WorkspaceId.SETTINGS
    while focused() is not window.stop_button:
        press(focused(), Qt.Key.Key_Tab)
    press(window.stop_button, Qt.Key.Key_Space)
    assert wait_until(lambda: not window.capture.running)
    press(focused(), Qt.Key.Key_1, Qt.KeyboardModifier.ControlModifier)
    assert window.current_workspace() is CONVERSATION and elided(window) == []
