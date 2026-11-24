"""CAP-0172 WI-02: the Text translation page through the real MainWindow (offscreen, spies)."""

from __future__ import annotations

import pytest

from lianiq.ui import strings
from lianiq.ui.shell.workspaces import EntryState, WorkspaceId, entry
from tests._spy_window import build_window, spies  # noqa: F401 - pytest fixture
from tests.ui._language_helpers import wait_until


@pytest.fixture
def window(tmp_path, spies, monkeypatch):  # noqa: F811 - the spies fixture
    window = build_window(tmp_path, monkeypatch, provisioned=False)
    yield window
    window.close()


def page(window):
    window.navigation.select_index(2)  # Ctrl+3 runs the same call
    return window.text_translation


def type_text(workspace, text: str) -> None:
    workspace.source_edit.setFocus()
    workspace.source_edit.insertPlainText(text)


def ctrl_return(workspace) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    QTest.keyClick(workspace.source_edit, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)


def translated(workspace) -> bool:
    return not workspace.controller.translating and workspace.result_edit.toPlainText() != ""


def test_ac01_the_entry_is_enabled_third_and_opens_the_page(window) -> None:
    from PySide6.QtWidgets import QApplication

    assert entry(WorkspaceId.TEXT_TRANSLATION).state is EntryState.ENABLED
    workspace = page(window)
    assert window.current_workspace() is WorkspaceId.TEXT_TRANSLATION
    window.activateWindow()
    assert wait_until(lambda: QApplication.focusWidget() is workspace.source_edit)


def test_ac02_combos_list_registry_names_with_planned_disabled(window) -> None:
    workspace = page(window)
    names = [workspace.source_combo.itemText(i) for i in range(workspace.source_combo.count())]
    assert names[:3] == ["German", "English", "Mandarin (Simplified)"]
    planned = [i for i, name in enumerate(names) if name.endswith(strings.PAIR_PLANNED_SUFFIX)]
    assert planned
    model = workspace.source_combo.model()
    assert not any(model.item(i).isEnabled() for i in planned)
    assert workspace.source_combo.currentText() == "German"
    assert workspace.target_combo.currentText() == "Mandarin (Simplified)"


def test_ac04_ac05_ac07_typing_never_translates_and_ctrl_return_does_once(window, spies) -> None:  # noqa: F811
    workspace = page(window)
    type_text(workspace, "Hallo Welt.")
    assert spies.translator is None or spies.translator.calls == []
    ctrl_return(workspace)
    assert wait_until(lambda: translated(workspace))
    assert workspace.result_edit.toPlainText() == "[de>zh-Hans] Hallo Welt."
    assert spies.translator.calls == [("Hallo Welt.", "de>zh-Hans", ())]
    assert spies.constructed == ["translator"]  # no recogniser or synthesiser (AC-07)
    assert workspace.copy_translation_button.isEnabled()
    assert workspace.stale_label.isHidden()


def test_ac03_ac16_swap_keeps_the_draft_and_marks_the_result_stale(window) -> None:
    workspace = page(window)
    type_text(workspace, "Guten Tag.")
    workspace.translate_button.click()
    assert wait_until(lambda: translated(workspace))
    workspace.swap_button.click()
    assert workspace.source_combo.currentText() == "Mandarin (Simplified)"
    assert workspace.target_combo.currentText() == "German"
    assert workspace.source_edit.toPlainText() == "Guten Tag."
    assert not workspace.stale_label.isHidden()
    assert not workspace.copy_translation_button.isEnabled()


def test_choosing_the_other_language_in_a_combo_swaps_them(window) -> None:
    workspace = page(window)
    workspace.source_combo.setCurrentIndex(2)
    workspace.source_combo.activated.emit(2)
    assert workspace.controller.draft.source == "zh-Hans"
    assert workspace.target_combo.currentText() == "German"


def test_ac11_ac12_empty_and_over_limit_block_translate(window, spies) -> None:  # noqa: F811
    workspace = page(window)
    assert not workspace.translate_button.isEnabled()
    assert workspace.readiness_label.text() == strings.TEXT_EMPTY_REASON
    type_text(workspace, "x" * 5_001)
    assert not workspace.translate_button.isEnabled()
    assert workspace.readiness_label.text().startswith("Too long to translate: 5001")
    ctrl_return(workspace)
    assert spies.translator is None
    assert len(workspace.source_edit.toPlainText()) == 5_001  # never cut


def test_ac22_copy_writes_exactly_the_texts(window) -> None:
    from PySide6.QtGui import QGuiApplication

    workspace = page(window)
    assert not workspace.copy_translation_button.isEnabled()
    type_text(workspace, "Kopieren.")
    workspace.copy_source_button.click()
    assert QGuiApplication.clipboard().text() == "Kopieren."
    workspace.translate_button.click()
    assert wait_until(lambda: translated(workspace))
    workspace.copy_translation_button.click()
    assert QGuiApplication.clipboard().text() == "[de>zh-Hans] Kopieren."


def test_ac14_rtl_paragraphs_use_automatic_direction(window) -> None:
    from PySide6.QtCore import Qt

    workspace = page(window)
    for editor in (workspace.source_edit, workspace.result_edit):
        option = editor.document().defaultTextOption()
        assert option.textDirection() == Qt.LayoutDirection.LayoutDirectionAuto
