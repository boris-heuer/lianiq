"""Main window language controls (CAP-0169 WI-06; spec §2.2-§2.5, contract.md §2.4).

pytest-qt style UI navigation: an offscreen ``MainWindow`` over spy adapters, driven by
its controls (mouse and keyboard). Covers AC-02, AC-03, AC-08, AC-13, AC-18 (UI labels)
and AC-19; AC-11 is in ``test_main_window_languages_held.py``, AC-22 and VoR-01 in
``test_main_window_languages_stop.py``, the shared helpers in ``_language_helpers.py``.
These are code evidence only, not native Windows product evidence (WI-08).
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from lianiq.languages import (
    BUILTIN_REGISTRY,
    DirectedEdge,
    OutputKind,
    PairLockedError,
    PlannedLanguageError,
    ReadinessStatus,
    SameLanguagePairError,
)
from lianiq.ui import strings
from tests._spy_window import spies  # noqa: F401
from tests.ui._language_helpers import (
    AUTOMATIC,
    DE,
    DE_TO_ZH,
    LOCKED,
    PAIR_NAME,
    PLANNED,
    ZH,
    ZH_TO_DE,
    assert_no_language_codes,
    blocks,
    click,
    item_enabled,
    items,
    language_window,  # noqa: F401
    only_de_to_zh_edge,
    open_window,
    press,
    start,
    submit,
    transcript,
    wait_until,
    without_mandarin_voice,
)

# AC-02 / E-01 -----------------------------------------------------------------------------


def test_ac02_planned_languages_are_listed_but_cannot_be_selected(window) -> None:
    from PySide6.QtCore import Qt

    combo = window.pair_combo
    assert combo.accessibleName() == "Language pair"
    assert items(combo) == [PAIR_NAME, *PLANNED]
    assert combo.currentText() == PAIR_NAME
    assert window.windowTitle() == f"lianiq · {PAIR_NAME}"
    for index in range(1, combo.count()):
        flags = combo.model().item(index).flags()
        assert not flags & Qt.ItemFlag.ItemIsEnabled
        assert not flags & Qt.ItemFlag.ItemIsSelectable
        assert "planned, unavailable" in combo.itemText(index)  # state in text, not colour

    # Keyboard navigation cannot select a planned entry.
    combo.setFocus()
    for key in (Qt.Key.Key_Down, Qt.Key.Key_End, Qt.Key.Key_PageDown):
        press(combo, key)
        assert combo.currentIndex() == 0
    assert window.current_pair() == BUILTIN_REGISTRY.pair(DE, ZH)


def test_ac02_registry_rejects_planned_and_same_language_pairs() -> None:
    with pytest.raises(PlannedLanguageError):
        BUILTIN_REGISTRY.pair("de", "en")
    with pytest.raises(SameLanguagePairError):
        BUILTIN_REGISTRY.pair("de", "de")


# E-02 / AC-18 (UI) ------------------------------------------------------------------------


def test_routing_entries_and_result_labels_use_registry_names(window, spies) -> None:  # noqa: F811
    assert items(window.mode_combo) == [AUTOMATIC, DE_TO_ZH, ZH_TO_DE]
    assert all(item_enabled(window.mode_combo, index) for index in range(3))
    assert window.mode_combo.currentText() == AUTOMATIC
    assert_no_language_codes(window)

    start(window)
    submit(window, spies, transcript("Guten Tag", "de"))
    assert wait_until(lambda: len(window.history) == 1)
    submit(window, spies, transcript("你好", "zh-Hans"))
    assert wait_until(lambda: len(window.history) == 2)

    assert blocks(window.source_text) == [
        "German: Guten Tag",
        "Mandarin (Simplified): 你好",
    ]
    assert blocks(window.target_text) == [
        "Mandarin (Simplified): [de>zh-Hans] Guten Tag",
        "German: [zh-Hans>de] 你好",
    ]
    assert window.latency_label.text().startswith(ZH_TO_DE + " · ")
    assert_no_language_codes(window)
    window.stop_listening()


# AC-03 / VoR-02 / E-08 --------------------------------------------------------------------


def test_ac03_vor02_missing_reverse_edge_blocks_automatic_and_the_fixed_direction_works(
    tmp_path,
    monkeypatch,
    request,
    spies,  # noqa: F811
) -> None:
    window = open_window(tmp_path, monkeypatch, request, configure=only_de_to_zh_edge)
    missing = "Not available: missing translation Mandarin (Simplified) → German"

    reverse = window.pipeline.catalog.translation(DirectedEdge(ZH, DE))
    assert reverse.status is ReadinessStatus.NOT_CONFIGURED
    assert window.current_pair() is not None  # the pair is ready through one direction
    assert window.mode_combo.currentText() == AUTOMATIC  # the saved routing
    assert not item_enabled(window.mode_combo, 0)
    assert window.mode_combo.model().item(0).toolTip() == missing
    assert item_enabled(window.mode_combo, 1)
    assert not item_enabled(window.mode_combo, 2)
    assert not window.start_button.isEnabled()
    assert window.statusBar().currentMessage() == missing

    click(window.swap_button)  # Automatic -> the first available fixed direction
    assert window.mode_combo.currentText() == DE_TO_ZH
    assert window.start_button.isEnabled()
    click(window.swap_button)  # the reverse direction is unavailable: no change
    assert window.mode_combo.currentText() == DE_TO_ZH
    # CAP-0168 WI-03: the refusal is an info notice naming the missing item.
    notice = window.conversation_notice()
    assert notice.title == missing and notice.severity.name == "INFO"

    start(window)
    assert spies.recognizer.warmed_languages == ["de"]
    assert spies.translator.warmed_edges == ["de>zh-Hans"]
    assert spies.synthesizer is None
    submit(window, spies, transcript("Guten Tag", "de"))
    assert wait_until(lambda: len(window.history) == 1)
    assert spies.recognizer.calls == ["de"]
    assert (window.history[0].source_language, window.history[0].target_language) == (DE, ZH)
    assert [call[1] for call in spies.translator.calls] == ["de>zh-Hans"]
    window.stop_listening()


# AC-08 ------------------------------------------------------------------------------------


def test_ac08_automatic_text_starts_and_voice_output_names_the_missing_voice(
    tmp_path,
    monkeypatch,
    request,
    spies,  # noqa: F811
) -> None:
    window = open_window(tmp_path, monkeypatch, request, configure=without_mandarin_voice)

    assert window.mode_combo.currentText() == AUTOMATIC
    assert not window.tts_checkbox.isEnabled()
    assert window.tts_checkbox.toolTip() == "Not available: missing voice Mandarin (Simplified)"
    assert not window.tts_checkbox.isChecked()  # spoken output is unavailable
    assert window.start_button.isEnabled()

    start(window)
    assert window.session_controller.session.mode.output is OutputKind.TEXT
    assert window.pipeline.voice_output is False
    submit(window, spies, transcript("Guten Tag", "de"))
    assert wait_until(lambda: len(window.history) == 1)
    assert spies.synthesizer is None  # no voice constructed, loaded or used
    window.stop_listening()

    # The fixed direction to German needs only the German voice: Voice output is offered,
    # and the saved preference (spoken) applies again.
    window.mode_combo.setCurrentText(ZH_TO_DE)
    assert window.tts_checkbox.isEnabled()
    assert window.tts_checkbox.toolTip() == ""
    assert window.tts_checkbox.isChecked()
    assert window.config.voice_output is True


# AC-13 / E-03 -----------------------------------------------------------------------------


def test_ac13_pair_routing_switch_and_voice_output_are_locked_while_running(window) -> None:
    session_controls = (
        window.pair_combo,
        window.mode_combo,
        window.swap_button,
        window.tts_checkbox,
    )
    assert all(control.isEnabled() for control in session_controls)

    start(window)

    for control in session_controls:
        assert not control.isEnabled()
        assert control.toolTip() == LOCKED
    other = window._conversation_session(window.current_pair(), DE, OutputKind.TEXT)
    with pytest.raises(PairLockedError, match=LOCKED):
        window.session_controller.change(other)

    click(window.stop_button)

    for control in session_controls:
        assert control.isEnabled()
        assert control.toolTip() != LOCKED
    window.mode_combo.setCurrentText(DE_TO_ZH)  # Stop -> change -> Start applies it
    start(window)
    assert window.session_controller.session.fixed_source == DE
    window.stop_listening()


# AC-19 ------------------------------------------------------------------------------------


def test_ac19_no_ready_pair_disables_start_with_the_no_pair_message(
    tmp_path,
    monkeypatch,
    request,
    spies,  # noqa: F811
) -> None:
    window = open_window(tmp_path, monkeypatch, request, provisioned=False)

    assert items(window.pair_combo) == ["No ready language pair", *PLANNED]
    assert not item_enabled(window.pair_combo, 0)
    assert window.current_pair() is None
    assert not window.start_button.isEnabled()
    assert window.statusBar().currentMessage() == strings.NO_PAIR_READY
    assert window.statusBar().currentMessage() == (
        "No language pair is ready. Provision languages first (Language readiness)."
    )
    click(window.start_button)
    assert spies.constructed == []


def test_missing_microphone_disables_start_and_names_it(
    tmp_path,
    monkeypatch,
    request,
    spies,  # noqa: F811
) -> None:
    window = open_window(tmp_path, monkeypatch, request)
    window.devices = []  # no capture or playback device enumerated
    window._refresh_availability()

    assert not window.start_button.isEnabled()
    assert window.statusBar().currentMessage() == "Not available: missing microphone"
