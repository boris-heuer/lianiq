"""Meeting workspace setup: entry, devices, options and Start availability (CAP-0177 WI-04).

pytest-qt style offscreen UI tests over spy adapters (``_meeting_window.py``). The Unit
halves of AC-01, AC-02, AC-03, AC-25 and AC-28 are in ``tests/meeting/test_contracts.py``,
``tests/languages/test_requirements_meeting.py`` and ``tests/test_config_meeting.py``
(WI-01/WI-02). AC-19 and AC-22 are in ``test_meeting_workspace_session.py``.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from lianiq.meeting.contracts import TableInputDuringOutput
from lianiq.ui.shell.workspaces import DEFAULT_ENTRIES, EntryState, WorkspaceId
from tests._spy_window import spies  # noqa: F401
from tests.ui._meeting_window import (
    HEADSET,
    JABRA_MIC,
    JABRA_SPEAKER,
    LAPTOP_MIC,
    LOCAL,
    MEETING,
    SPEAKER,
    TABLE,
    USER,
    assign_table,
    availability,
    build_meeting_window,
    choose,
    end_and_wait,
    meeting_window,  # noqa: F401
    start_meeting,
)
from tests.ui._navigation_helpers import activate, press
from tests.ui.test_main_window_session import click

PAIR = "German ↔ Mandarin (Simplified)"
FOLLOW = "Follow Windows default (now: Microphone Array (Realtek Audio))"

# AC-29 --------------------------------------------------------------------------------------


def test_ac29_meeting_is_the_second_entry_enabled_and_ctrl_2_opens_it(window) -> None:
    from PySide6.QtCore import Qt

    assert [item.id for item in DEFAULT_ENTRIES][:2] == [WorkspaceId.CONVERSATION, MEETING]
    assert DEFAULT_ENTRIES[1].state is EntryState.ENABLED
    others = [(item.id, item.state) for item in DEFAULT_ENTRIES if item.id is not MEETING]
    assert others == [
        (WorkspaceId.CONVERSATION, EntryState.ENABLED),
        (WorkspaceId.TEXT_TRANSLATION, EntryState.ENABLED),  # CAP-0172
        (WorkspaceId.LISTEN, EntryState.ENABLED),  # CAP-0170
        (WorkspaceId.CALL_BRIDGE, EntryState.EXPERIMENTAL),
        (WorkspaceId.LANGUAGE_PACKS, EntryState.ENABLED),
        (WorkspaceId.SETTINGS, EntryState.ENABLED),
    ]
    button = window.navigation.buttons[MEETING]
    assert button.isEnabled() and button.text() == "Meeting"
    window.show_workspace(WorkspaceId.CONVERSATION)
    activate(window)
    control = Qt.KeyboardModifier.ControlModifier
    press(window.focusWidget() or window, Qt.Key.Key_2, control)
    assert window.current_workspace() is MEETING and button.isChecked()
    for position, item in enumerate(DEFAULT_ENTRIES, start=1):
        before = window.current_workspace()
        press(window.focusWidget() or window, getattr(Qt.Key, f"Key_{position}"), control)
        assert window.current_workspace() is (item.id if item.selectable else before)


def test_ac29_uia_the_entry_and_every_meeting_control_are_named(window) -> None:
    """What the UI Automation bridge reads (Qt's accessibility interface), as E-01 does."""
    from PySide6.QtGui import QAccessible
    from PySide6.QtWidgets import QAbstractButton, QComboBox

    entry = QAccessible.queryAccessibleInterface(window.navigation.buttons[MEETING])
    assert entry.text(QAccessible.Text.Name) == "Meeting"
    assert not entry.state().disabled
    page, banner = window.workspace_pages[MEETING], window.banners[MEETING]
    controls = [*page.findChildren(QComboBox), *page.findChildren(QAbstractButton)]
    controls = [control for control in controls if not banner.isAncestorOf(control)]
    assert len(controls) == 12  # pair, 4 devices, headset, Refresh, speech, 2 radios, Start, End
    for control in controls:
        name = QAccessible.queryAccessibleInterface(control).text(QAccessible.Text.Name)
        assert name.strip(), control


# AC-01 --------------------------------------------------------------------------------------


def test_ac01_the_page_offers_the_four_devices_and_shows_the_session_pair(window) -> None:
    meeting = window.meeting
    names = {role: combo.accessibleName() for role, combo in meeting.combos.items()}
    assert names == {
        TABLE: "Table microphone",
        SPEAKER: "Table speaker",
        USER: "Your microphone",
        LOCAL: "Output for German speech",
    }
    assert all(combo.isVisible() for combo in meeting.combos.values())
    assert meeting.combos[USER].currentText() == FOLLOW  # follows the Windows default
    assert window.config.meeting.user_input_policy == "follow_default"
    assert meeting.endpoint(USER) == LAPTOP_MIC
    assert meeting.pair_combo.currentText() == PAIR == window.pair_combo.currentText()
    assert meeting.speak_local_checkbox.text() == "Speak German for me"
    assert not meeting.speak_local_checkbox.isChecked()
    during = "Table microphone while Lianiq speaks Mandarin (Simplified)"
    assert meeting.table_during_label.text() == during
    assert window.pipeline.recognizer is None  # no model is loaded before Start


def test_choosing_a_table_endpoint_suggests_its_partner_and_can_be_overridden(window) -> None:
    meeting = window.meeting
    choose(window, SPEAKER, JABRA_SPEAKER)
    assert meeting.combos[TABLE].currentData() == JABRA_MIC.endpoint_id  # the suggestion
    choose(window, SPEAKER, HEADSET)  # the PO overrides it
    assert window.config.meeting.table_render_endpoint_id == HEADSET.endpoint_id
    assert window.config.meeting.table_capture_endpoint_id == JABRA_MIC.endpoint_id


# AC-02 --------------------------------------------------------------------------------------


def test_ac02_start_is_disabled_and_lists_the_missing_table_devices(window) -> None:
    meeting = window.meeting
    assert not meeting.start_button.isEnabled()
    assert availability(window) == "Not available: missing table microphone, table speaker"
    assign_table(window)
    assert meeting.start_button.isEnabled() and availability(window) == ""


def _without_reverse_edge(config, _root) -> None:
    del config.translation.edges["zh-Hans>de"]


def _without_table_voice(config, _root) -> None:
    del config.tts.voices["zh-Hans"]


@pytest.mark.parametrize(
    ("options", "missing"),
    [
        (
            {"provisioned": False},
            (
                "speech recognition German, speech recognition Mandarin (Simplified), "
                "voice Mandarin (Simplified)"
            ),
        ),
        ({"configure": _without_reverse_edge}, "translation Mandarin (Simplified) → German"),
        ({"configure": _without_table_voice}, "voice Mandarin (Simplified)"),
    ],
)
def test_ac02_each_missing_model_is_listed(tmp_path, spies, monkeypatch, options, missing) -> None:  # noqa: F811
    window = build_meeting_window(tmp_path, monkeypatch, **options)
    try:
        assign_table(window)
        assert not window.meeting.start_button.isEnabled()
        assert availability(window) == f"Not available: missing {missing}"
    finally:
        window.close()


# AC-03 --------------------------------------------------------------------------------------


def test_ac03_your_microphone_following_the_default_to_the_table_mic_blocks_start(
    window,
) -> None:
    meeting = window.meeting
    choose(window, TABLE, LAPTOP_MIC)  # the Windows default input is the table microphone
    choose(window, SPEAKER, JABRA_SPEAKER)
    assert not meeting.start_button.isEnabled()
    assert availability(window) == "Your microphone is the table microphone"
    choose(window, SPEAKER)  # a missing item and the conflict: both are listed
    assert availability(window) == (
        "Not available: missing table speaker\nYour microphone is the table microphone"
    )
    choose(window, SPEAKER, JABRA_SPEAKER)
    assert "user_capture" not in meeting.device_readiness().meeting_endpoints
    choose(window, USER, JABRA_MIC)  # explicit: no conflict any more
    assert meeting.start_button.isEnabled() and availability(window) == ""


def test_ac03_an_explicit_your_microphone_equal_to_the_table_mic_blocks_start(window) -> None:
    assign_table(window)
    choose(window, USER, JABRA_MIC)
    assert window.config.meeting.user_input_policy == "explicit"
    assert not window.meeting.start_button.isEnabled()
    assert "Your microphone is the table microphone" in availability(window)
    choose(window, USER)  # back to following the default (the laptop microphone)
    assert window.config.meeting.user_input_policy == "follow_default"
    assert window.meeting.start_button.isEnabled()


# AC-25 --------------------------------------------------------------------------------------


def test_ac25_table_input_option_defaults_to_muted_saves_open_and_locks_while_running(
    window,
) -> None:
    meeting = window.meeting
    mute = meeting.table_mode_buttons[TableInputDuringOutput.MUTE]
    open_ = meeting.table_mode_buttons[TableInputDuringOutput.OPEN]
    assert mute.text() == "Muted (recommended)" and mute.isChecked()
    assert open_.text() == "Open — relies on the speakerphone's echo cancellation"
    assert window.config.meeting.table_input_during_output == "mute"
    click(open_)
    assert open_.isChecked() and window.config.meeting.table_input_during_output == "open"
    assign_table(window)
    start_meeting(window)
    _session, _endpoints, options = window.meeting_factory.calls[-1]
    assert options.table_input_during_output is TableInputDuringOutput.OPEN
    for button in (mute, open_):
        assert not button.isEnabled()
        assert button.toolTip() == "Available when no meeting is running"
    end_and_wait(window)
    assert mute.isEnabled() and open_.isEnabled() and mute.toolTip() == ""


# AC-28 --------------------------------------------------------------------------------------


def test_ac28_speech_output_on_the_table_speaker_disables_the_switch_not_start(window) -> None:
    meeting = window.meeting
    assign_table(window)
    checkbox = meeting.speak_local_checkbox
    assert not checkbox.isEnabled()
    assert checkbox.toolTip() == "Not available: missing output for German speech"
    choose(window, LOCAL, JABRA_SPEAKER)
    assert not checkbox.isEnabled()
    assert checkbox.toolTip() == "German speech cannot use the table speaker"
    assert meeting.start_button.isEnabled()
    choose(window, LOCAL, HEADSET)
    assert checkbox.isEnabled() and checkbox.toolTip() == ""
    checkbox.click()
    assert checkbox.isChecked() and window.config.meeting.speak_local
    choose(window, LOCAL, JABRA_SPEAKER)  # the preference is kept, the switch is off
    assert not checkbox.isChecked() and window.config.meeting.speak_local


def test_the_headset_mark_is_saved_and_reaches_the_controller(window) -> None:
    meeting = window.meeting
    assert not meeting.headset_checkbox.isChecked()
    assign_table(window)
    choose(window, LOCAL, HEADSET)
    meeting.headset_checkbox.click()
    assert window.config.meeting.local_output_is_headset
    start_meeting(window)
    _session, endpoints, _options = window.meeting_factory.calls[-1]
    assert endpoints.local_render == HEADSET and endpoints.local_render_is_headset


def test_without_a_controller_factory_start_reports_it_and_opens_nothing(window) -> None:
    from tests.ui._meeting_window import notice_title, wait_until

    window.meeting_factory = None
    assign_table(window)
    assert window.meeting.combos[LOCAL].itemText(0) == "Choose device"
    click(window.meeting.start_button)
    expected = "Meeting could not start: No meeting controller is configured in this build"
    assert wait_until(lambda: notice_title(window, MEETING) == expected)
    assert window.meeting.controller is None and not window.meeting.active()
    assert window.session_owner.state.value == "idle"
