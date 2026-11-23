"""Accessible names and keyboard paths of the voice row and its dialog (CAP-0167 AC-22).

Read through Qt's accessibility interface, the one its UI Automation bridge exposes: the
contract.md §9 names of the switches, state labels, **Replay**, **Stop playback**,
**Voice options…** and the dialog's Voice, Rate, Volume and Close, in Conversation and in
Settings › Voice output; no Tab stop of the row or the dialog is unnamed; Space toggles a
switch and opens the dialog, the arrow keys move Rate, Escape closes it. Narrator (e2e
plan E-08) is the native half.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from lianiq.tts.voice_controls import VoiceControls
from lianiq.ui.shell.workspaces import WorkspaceId
from tests._spy_window import spies  # noqa: F401
from tests.languages.synthetic import QAA, QAB
from tests.ui._language_helpers import press, wait_until
from tests.ui.test_main_window_accessibility import accessible_name
from tests.ui.test_voice_options import with_controls
from tests.ui.test_voice_output import NAME, open_window, rows  # noqa: F401

CONTROLS = {QAA: VoiceControls(3, rate=True, volume=True), QAB: VoiceControls(1, True, False)}


def description(widget) -> str:
    from PySide6.QtGui import QAccessible

    return QAccessible.queryAccessibleInterface(widget).text(QAccessible.Text.Description)


def unnamed_tab_stops(container) -> list[str]:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QWidget

    return [
        type(widget).__name__
        for widget in container.findChildren(QWidget)
        if widget.isVisibleTo(container)
        and widget.focusPolicy() & Qt.FocusPolicy.TabFocus
        and widget.focusProxy() is None
        and not accessible_name(widget).strip()
    ]


def test_ac22_the_voice_row_has_the_contract_names_in_conversation_and_settings(
    open_window,  # noqa: F811
) -> None:
    window = open_window(QAA, QAB)
    with_controls(window, CONTROLS)
    for voice_rows in (rows(window), window.settings.voice_rows):
        for language in (QAA, QAB):
            name, label = NAME[language], voice_rows.state_label(language)
            assert accessible_name(voice_rows.switch(language)) == f"Speak {name}"
            assert accessible_name(label) == f"{name} voice: {label.text()}"
            assert accessible_name(voice_rows.options_button(language)) == (
                f"Voice options for {name}"
            )
        assert accessible_name(voice_rows.replay_button) == "Replay"
        assert accessible_name(voice_rows.stop_playback_button) == "Stop playback"
        assert unnamed_tab_stops(voice_rows) == []


def test_ac22_keyboard_toggles_a_switch_and_opens_moves_and_closes_the_dialog(
    open_window,  # noqa: F811
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QPushButton

    window = open_window(QAA, QAB)
    with_controls(window, CONTROLS)
    window.show_workspace(WorkspaceId.CONVERSATION)
    switch = rows(window).switch(QAB)
    press(switch, Qt.Key.Key_Space)
    assert not switch.isChecked() and window.config.tts.output[QAB].enabled is False
    press(switch, Qt.Key.Key_Space)
    assert switch.isChecked()

    press(rows(window).options_button(QAA), Qt.Key.Key_Space)
    dialog = window.conversation.voice_dialog
    assert dialog is not None and wait_until(dialog.isVisible)
    assert accessible_name(dialog) == f"Voice options — {NAME[QAA]}"
    assert accessible_name(dialog.voice_combo) == "Voice"
    assert (accessible_name(dialog.rate_slider), description(dialog.rate_slider)) == (
        "Rate",
        "1.00×",
    )
    assert (accessible_name(dialog.volume_slider), description(dialog.volume_slider)) == (
        "Volume",
        "100 %",
    )
    assert unnamed_tab_stops(dialog) == []
    buttons = dialog.findChildren(QPushButton)
    assert [accessible_name(button) for button in buttons] == ["Close"]
    press(dialog.rate_slider, Qt.Key.Key_Right)
    assert description(dialog.rate_slider) == "1.05×"
    press(dialog, Qt.Key.Key_Escape)
    assert wait_until(lambda: not dialog.isVisible())
