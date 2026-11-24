"""CAP-0170 WI-03: the Listen & translate page through the real ``MainWindow`` (offscreen)."""
# ruff: noqa: F811 - ``spies`` is the imported fixture

from __future__ import annotations

import json

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt

from lianiq.listen.lifecycle import ListenPhase
from lianiq.listen.transcript import SegmentState
from lianiq.ui import strings
from lianiq.ui.shell.workspaces import DEFAULT_ENTRIES, EntryState, WorkspaceId
from lianiq.ui.workspaces.listen_model import right_to_left
from lianiq.ui.workspaces.listen_selection import MISSING
from tests._fake_devices import SPEAKERS
from tests._spy_window import spies  # noqa: F401 - the fixture
from tests.ui._language_packs_helpers import wait_until
from tests.ui._listen_helpers import listen_window, phase_is, speak, start, states

LISTEN = WorkspaceId.LISTEN


@pytest.fixture
def window(tmp_path, monkeypatch, spies):
    window = listen_window(tmp_path, monkeypatch)
    yield window
    window.listen.shutdown()
    window.close()


def test_ac01_the_entry_is_enabled_fourth_and_opens_without_capture(window) -> None:
    assert DEFAULT_ENTRIES[3].id is LISTEN and DEFAULT_ENTRIES[3].state is EntryState.ENABLED
    window.show_workspace(WorkspaceId.CONVERSATION)
    window.navigation.select_index(3)
    assert window.current_workspace() is LISTEN
    assert window.listen_captures == []
    assert window.listen.start_button.isEnabled()
    assert window.listen.state_label.text() == strings.LISTEN_STATE_READY
    assert window.listen.empty_label.text() == strings.LISTEN_EMPTY


@pytest.mark.parametrize("size", [(850, 560), (1280, 720)])
def test_ac02_the_controls_are_visible_at_both_sizes(window, size) -> None:
    window.resize(*size)
    page = window.listen
    for widget in (
        page.source_combo,
        page.swap_button,
        page.target_combo,
        page.microphone_combo,
        page.start_button,
        page.transcript_view,
    ):
        assert widget.isVisible() and widget.width() > 0, widget.accessibleName()
        right = widget.mapTo(page.page, widget.rect().topRight()).x()
        assert right <= page.page.width(), widget.accessibleName()
    names = [page.source_combo.itemText(i) for i in range(page.source_combo.count())]
    assert names[:3] == ["German", "English", "Mandarin (Simplified)"]
    planned = [i for i, name in enumerate(names) if strings.PAIR_PLANNED_SUFFIX in name]
    assert planned and not page.source_combo.model().item(planned[0]).isEnabled()


def test_ac03_ac06_three_segments_become_rows_and_no_voice_is_built(window, spies) -> None:
    start(window)  # F8 on the page
    assert window.listen_captures[0].running
    assert sorted(spies.constructed) == ["recognizer", "translator"]
    speak(window, spies, "Eins.", "Zwei.", "Drei.")
    assert wait_until(lambda: states(window) == [SegmentState.DONE] * 3)
    rows = window.listen.controller.transcript.rows
    assert [row.source_text for row in rows] == ["Eins.", "Zwei.", "Drei."]
    assert {(row.result.source_language, row.result.target_language) for row in rows} == {
        ("de", "zh-Hans")
    }
    text = window.listen.model.index(0).data()
    assert "German" in text and "Eins." in text and "[de>zh-Hans] Eins." in text
    window.stop_active_session()
    assert phase_is(window, ListenPhase.IDLE)
    assert window.listen.state_label.text() == strings.LISTEN_STATE_STOPPED
    assert "synthesizer" not in spies.constructed


def test_ac07_empty_recognition_is_not_understood_without_a_translation(window, spies) -> None:
    start(window)
    speak(window, spies, "")
    assert wait_until(lambda: states(window) == [SegmentState.NOT_UNDERSTOOD])
    assert spies.recognizer.calls == ["de"]
    assert spies.translator.calls == []
    assert strings.LISTEN_NOT_UNDERSTOOD in window.listen.model.index(0).data()


def test_ac05_without_a_microphone_start_is_disabled_with_the_link(window) -> None:
    window.fake_devices.set(SPEAKERS)
    window.device_setup.load()
    window.listen.refresh()
    page = window.listen
    assert not page.start_button.isEnabled()
    assert page.readiness_label.text() == strings.LISTEN_MIC_MISSING
    assert page.open_audio_button.isVisible()
    page.open_audio_button.click()
    assert window.current_workspace() is WorkspaceId.SETTINGS


def test_ac08_selectors_lock_while_running_and_rows_keep_their_languages(window, spies) -> None:
    start(window)
    page = window.listen
    for widget in (page.source_combo, page.target_combo, page.swap_button, page.microphone_combo):
        assert not widget.isEnabled() and widget.toolTip() == strings.LISTEN_LOCKED
    speak(window, spies, "Hallo.")
    assert wait_until(lambda: states(window) == [SegmentState.DONE])
    window.stop_active_session()
    assert phase_is(window, ListenPhase.IDLE)
    page.swap_button.click()
    assert (page.source, page.target) == ("zh-Hans", "de")
    assert (window.config.listen.source_language, window.config.listen.target_language) == (
        "zh-Hans",
        "de",
    )
    row = page.controller.transcript.rows[0]
    assert (row.source_language, row.target_language) == ("de", "zh-Hans")
    assert page.model.index(0).data().startswith(row.captured_at.strftime("%H:%M:%S") + " · German")


def test_ac19_choices_are_saved_without_text_and_preselected(tmp_path, monkeypatch, spies) -> None:
    def configure(config, _root) -> None:
        config.listen.source_language, config.listen.target_language = "zh-Hans", "de"
        config.listen.input_policy, config.listen.input_endpoint_id = "explicit", "{gone}"

    window = listen_window(tmp_path, monkeypatch, configure=configure)
    page = window.listen
    try:
        assert (page.source_combo.currentData(), page.target_combo.currentData()) == (
            "zh-Hans",
            "de",
        )
        assert page.microphone_combo.currentData() == MISSING
        assert not page.start_button.isEnabled()
        page.microphone_combo.setCurrentIndex(1)
        page.microphone_combo.activated.emit(1)
        assert window.config.listen.input_policy == "explicit"
        assert page.start_button.isEnabled()
        path = tmp_path / "settings.local.json"
        window.config.save(path)
        saved = json.loads(path.read_text(encoding="utf-8"))["listen"]
        assert saved["input_endpoint_id"] == page.microphone_combo.currentData()
        assert set(saved) == {
            "source_language",
            "target_language",
            "input_policy",
            "input_endpoint_id",
        }
    finally:
        window.close()


def test_ac23_rtl_rows_align_right_and_text_is_unchanged(window, spies) -> None:
    assert right_to_left("مرحبا بالعالم") and not right_to_left("早上好")
    start(window)
    speak(window, spies, "مرحبا بالعالم", "早上好")
    assert wait_until(lambda: states(window) == [SegmentState.DONE] * 2)
    model = window.listen.model
    align = [model.index(row).data(Qt.ItemDataRole.TextAlignmentRole) for row in (0, 1)]
    assert align[0] & int(Qt.AlignmentFlag.AlignRight)
    assert align[1] & int(Qt.AlignmentFlag.AlignLeft)
    rows = window.listen.controller.transcript.rows
    assert [row.result.translated_text for row in rows] == [
        "[de>zh-Hans] مرحبا بالعالم",
        "[de>zh-Hans] 早上好",
    ]
    accessible = model.index(1).data(Qt.ItemDataRole.AccessibleTextRole)
    assert accessible.endswith("German: 早上好. Mandarin (Simplified): [de>zh-Hans] 早上好")
