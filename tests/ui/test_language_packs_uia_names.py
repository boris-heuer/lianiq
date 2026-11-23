"""CAP-0171 WI-07: AC-26 UIA names of the Language packs page, details dialog and assistant.

The tests read the Qt accessibility interface that Qt's UI Automation bridge exposes
(offscreen), so every control the spec names (spec §2.1-§2.3, contract §11) carries the
exact name from ``strings_packs``: accessible names equal the visible label, pack rows
"{pack name}, {state}", progress bars "{pack name} progress", the step list the step titles.
Every visible Tab stop of each surface has a name. The keyboard path of the details dialog
(Space ticks the licence, Enter downloads) and the banner action of the AC-31 notice are
driven through the real ``MainWindow``. The native Narrator pass is e2e plan row E-10.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QAccessible
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialogButtonBox, QGroupBox, QWidget

from lianiq.ui import strings
from lianiq.ui.setup_assistant import open_setup_assistant
from lianiq.ui.setup_assistant.assistant import AUDIO, LANGUAGES, REVIEW, TITLES
from lianiq.ui.shell.workspaces import WorkspaceId
from tests._spy_window import spies  # noqa: F401
from tests.packs.conftest import network_attempts  # noqa: F401
from tests.ui._language_packs_helpers import (  # noqa: F401 - the fixtures are imported
    ALL,
    MT,
    STT,
    open_page,
    packs_network,
    packs_shaped,
    packs_window,
    state,
    wait_until,
)
from tests.ui._notice_helpers import action


def name(widget) -> str:
    return QAccessible.queryAccessibleInterface(widget).text(QAccessible.Text.Name)


def unnamed_tab_stops(root: QWidget) -> list[str]:
    """Visible, enabled controls the Tab key reaches whose UIA name is empty."""
    stops = [
        widget
        for widget in root.findChildren(QWidget)
        if widget.isVisible()
        and widget.isEnabled()
        and widget.focusPolicy() & Qt.FocusPolicy.TabFocus
    ]
    return [type(widget).__name__ for widget in stops if not name(widget).strip()]


def test_ac26_language_packs_page_names(window) -> None:
    page = open_page(window)
    layout = page.layout
    content = layout.folder_label.parentWidget()
    assert name(layout.run_assistant_button) == strings.PACKS_RUN_ASSISTANT
    assert name(layout.folder_label) == layout.folder_label.text()
    assert layout.folder_label.text().startswith("Models folder: ")
    assert name(layout.empty_hint) == strings.PACK_EMPTY_HINT
    assert name(layout.planned_toggle) == strings.PACKS_GROUP_PLANNED
    groups = [name(group) for group in content.findChildren(QGroupBox)]
    assert groups == [
        strings.PACKS_GROUP_RECOGNITION,
        strings.PACKS_GROUP_TRANSLATION,
        strings.PACKS_GROUP_VOICES,
    ]
    for pack_id in ALL:
        row = page.rows[pack_id]
        assert name(row) == f"{row.name}, {strings.PACK_STATE_DOWNLOADABLE}"
        assert name(row.progress) == f"{row.name} progress"
        buttons = (row.primary_button, row.remove_button, row.import_button)
        assert [name(b) for b in (*buttons, row.retry_button, row.cancel_button)] == [
            strings.PACK_GET,
            strings.PACK_REMOVE,
            strings.PACK_IMPORT,
            strings.PACK_RETRY,
            strings.PACK_CANCEL,
        ]
    layout.planned_toggle.click()  # the expanded planned group adds only named texts
    assert unnamed_tab_stops(content) == []


def test_ac26_details_dialog_names_and_keyboard_download(window) -> None:
    page = open_page(window)
    page.rows[MT].primary_button.click()
    dialog = page.details
    assert dialog.focusWidget() is dialog.integrity_toggle  # focus on the first control
    licence = page.packs.get(MT).licence
    assert name(dialog.licence_box) == strings.PACK_ACCEPT_LICENCE.format(licence=licence)
    assert name(dialog.download_button) == strings.PACK_DOWNLOAD
    assert name(dialog.import_button) == strings.PACK_IMPORT
    assert name(dialog.integrity_toggle) == strings.PACK_DETAILS_INTEGRITY
    cancel = dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Cancel)
    assert name(cancel) == strings.PACK_CANCEL
    menu = [item.text() for item in dialog.import_button.menu().actions()]
    assert menu == [strings.PACK_IMPORT_FILE, strings.PACK_IMPORT_FOLDER]
    assert list(dialog.values) == [
        strings.PACK_DETAILS_SOURCE,
        strings.PACK_DETAILS_MODEL,
        strings.PACK_DETAILS_LOCALES,
        "Size",
        strings.PACK_DETAILS_FREE,
        strings.PACK_DETAILS_LICENCE,
        strings.PACK_DETAILS_CONSTRAINTS,
        "Needed by",
    ]
    assert all(name(value) == caption for caption, value in dialog.values.items())
    assert unnamed_tab_stops(dialog) == []

    QTest.keyClick(dialog.licence_box, Qt.Key.Key_Space)  # keyboard only (VoR-01)
    assert dialog.download_button.isEnabled()
    QTest.keyClick(dialog, Qt.Key.Key_Return)  # Enter = the default button, Download
    assert dialog.choice == ("download", None)
    assert wait_until(lambda: state(page, MT) == strings.PACK_STATE_VALIDATED)
    assert name(page.rows[MT]) == f"{page.rows[MT].name}, {strings.PACK_STATE_VALIDATED}"


def test_ac26_setup_assistant_names_on_every_step(window) -> None:
    assistant = open_setup_assistant(window)
    try:
        assert name(assistant) == strings.ASSIST_TITLE
        assert name(assistant.step_list) == strings.ASSIST_TITLE
        items = [assistant.step_list.item(i).text() for i in range(assistant.step_list.count())]
        assert items == list(TITLES)
        buttons = (assistant.skip_button, assistant.back_button, assistant.next_button)
        assert [name(b) for b in (*buttons, assistant.finish_button)] == [
            strings.ASSIST_SKIP,
            strings.ASSIST_BACK,
            strings.ASSIST_NEXT,
            strings.ASSIST_FINISH,
        ]
        boxes = {name(box) for box in assistant.usage.boxes.values()}
        assert {strings.USAGE_CONVERSATION, strings.USAGE_MEETING} <= boxes
        assert f"{strings.USAGE_CALL_BRIDGE} ({strings.ASSIST_EXPERIMENTAL})" in boxes
        assert unnamed_tab_stops(assistant) == []
        assistant.next_button.click()
        assert assistant.pages.currentIndex() == LANGUAGES
        assert [name(widget) for widget in assistant.languages.lists] == [
            strings.ASSIST_LANG_FIRST,
            strings.ASSIST_LANG_SECOND,
        ]
        assert unnamed_tab_stops(assistant) == []
        assistant.next_button.click()
        assert assistant.pages.currentIndex() == AUDIO
        audio = assistant.audio
        assert name(audio.test_mic_button) == strings.ASSIST_TEST_MIC
        assert name(audio.test_sound_button) == strings.ASSIST_TEST_SOUND
        assert unnamed_tab_stops(assistant) == []
        assistant.next_button.click()
        assert assistant.pages.currentIndex() == REVIEW
        assert wait_until(lambda: assistant.review.review is not None)
        assert {name(b) for b in assistant.review.get_buttons.values()} == {strings.PACK_GET}
        assert STT in assistant.review.get_buttons
        assert unnamed_tab_stops(assistant) == []
    finally:
        assistant.reject()


def test_ac31_banner_action_is_named_and_opens_language_packs(window) -> None:
    window.show_workspace(WorkspaceId.CONVERSATION)
    assert wait_until(lambda: window.banners[WorkspaceId.CONVERSATION].isVisible())
    button = action(window, strings.PACKS_OPEN)
    assert name(button) == strings.PACKS_OPEN
    button.click()
    assert window.current_workspace() is WorkspaceId.LANGUAGE_PACKS
