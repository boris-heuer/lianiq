"""Main window language controls (CAP-0169 WI-06; spec §2.2-§2.5, contract.md §2.4).

pytest-qt style UI navigation: an offscreen ``MainWindow`` over spy adapters, driven by
its controls (mouse and keyboard). Covers AC-02, AC-03, AC-08, AC-11, AC-13, AC-18 (UI
labels), AC-19, AC-22 and the value journeys VoR-01..VoR-03. These are code evidence only,
not native Windows product evidence (WI-08).
"""

from __future__ import annotations

import os
import re
import threading
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from lianiq.domain import AudioUtterance, Transcript
from lianiq.languages import (
    BUILTIN_REGISTRY,
    DirectedEdge,
    LanguageId,
    OutputKind,
    PairLockedError,
    PlannedLanguageError,
    ReadinessStatus,
    SameLanguagePairError,
)
from lianiq.ui import strings
from tests.test_requirement_scoped_loading import build_window, spies  # noqa: F401
from tests.ui.test_main_window_session import click, wait_until

DE = LanguageId("de")
ZH = LanguageId("zh-Hans")
EN = LanguageId("en")
AUDIO = AudioUtterance(np.zeros(1_600, dtype=np.float32), 16_000)
PAIR_NAME = "German ↔ Mandarin (Simplified)"
AUTOMATIC = "Automatic (German ↔ Mandarin (Simplified))"
DE_TO_ZH = "German → Mandarin (Simplified)"
ZH_TO_DE = "Mandarin (Simplified) → German"
PLANNED = [
    "English – planned, unavailable",
    "Spanish – planned, unavailable",
    "French – planned, unavailable",
]
LOCKED = "Stop the session to change language pair or mode"


def transcript(text: str, language: str | None, probability: float = 0.95, code: str = ""):
    detected = None if language is None else LanguageId(language)
    return Transcript(text, detected, probability, 0.1, code or (language or ""))


def items(combo) -> list[str]:
    return [combo.itemText(index) for index in range(combo.count())]


def blocks(editor) -> list[str]:
    """The result blocks of a text panel, in display order."""
    return [block.strip() for block in editor.toPlainText().split("\n\n") if block.strip()]


def item_enabled(combo, index: int) -> bool:
    return combo.model().item(index).isEnabled()


def press(widget, key) -> None:
    from PySide6.QtTest import QTest

    QTest.keyClick(widget, key)


def start(window) -> None:
    click(window.start_button)
    assert wait_until(lambda: window.capture.running)


def submit(window, spies, *results) -> None:  # noqa: F811
    spies.recognizer.results.extend(results)
    window.runner.submit(AUDIO)


def only_de_to_zh_edge(config, _root) -> None:
    """Settings with only the edge ``de>zh-Hans`` (AC-03, VoR-02)."""
    del config.translation.edges["zh-Hans>de"]


def without_mandarin_voice(config, _root) -> None:
    """Both STT languages and both edges, but no ``zh-Hans`` voice (AC-08)."""
    Path(config.tts.voices["zh-Hans"]).unlink()
    config.voice_output = True  # the saved preference is spoken output


@pytest.fixture
def window(tmp_path, spies, monkeypatch):  # noqa: F811
    window = build_window(tmp_path, monkeypatch)
    yield window
    window.close()


def open_window(tmp_path, monkeypatch, request, **options):
    window = build_window(tmp_path, monkeypatch, **options)
    request.addfinalizer(window.close)
    return window


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


def visible_texts(window) -> list[str]:
    from PySide6.QtWidgets import QAbstractButton, QComboBox, QLabel, QPlainTextEdit

    texts = [window.windowTitle(), window.statusBar().currentMessage()]
    for label in window.findChildren(QLabel):
        texts.append(label.text())
    for button in window.findChildren(QAbstractButton):
        texts += [button.text(), button.toolTip()]
    for combo in window.findChildren(QComboBox):
        texts += items(combo)
    for editor in window.findChildren(QPlainTextEdit):
        texts += [editor.toPlainText(), editor.placeholderText()]
    return texts


def assert_no_language_codes(window) -> None:
    for text in visible_texts(window):
        assert not re.search(r"\b(DE|ZH)\b", text), text


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
    assert window.statusBar().currentMessage() == missing

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


# AC-11 / VoR-03 / E-05 / E-06 -------------------------------------------------------------


@pytest.mark.parametrize(
    ("detected", "probability", "code", "shown"),
    [
        ("en", 0.95, "en", "Detected: English"),
        (None, 0.95, "xx", "Detected: xx"),
        ("de", 0.69, "de", "Detected: German"),
    ],
    ids=["out-of-pair", "unregistered", "low-confidence"],
)
def test_ac11_vor03_unclear_turn_is_held_until_translate_as_german_is_clicked(
    window,
    spies,  # noqa: F811
    detected,
    probability,
    code,
    shown,
) -> None:
    start(window)
    submit(window, spies, transcript("Good morning, this is a test.", detected, probability, code))

    bar = window.held_turn_bar
    assert wait_until(bar.isVisible)
    assert bar.title_label.text() == "Language unclear — choose the spoken language"
    assert bar.excerpt == "“Good morning, this is a test.”"
    assert bar.detected_label.text() == shown
    assert not bar.counter_label.isVisible()
    buttons = [*bar.translate_buttons.values(), bar.discard_button]
    assert [button.text() for button in buttons] == [
        "Translate as German",
        "Translate as Mandarin (Simplified)",
        "Discard",
    ]
    assert [button.accessibleName() for button in buttons] == [b.text() for b in buttons]
    assert spies.translator.calls == []  # nothing translated before the click
    assert window.history == []

    held = bar.turn
    spies.recognizer.results.append(transcript("Guten Morgen, das ist ein Test.", "de"))
    click(bar.translate_buttons[DE])

    assert wait_until(lambda: len(window.history) == 1)
    result = window.history[0]
    assert (result.turn_id, result.captured_at) == (held.turn_id, held.captured_at)
    assert (result.source_language, result.target_language) == (DE, ZH)
    assert spies.recognizer.calls == [None, "de"]  # forced re-recognition, no detection
    assert [call[1] for call in spies.translator.calls] == ["de>zh-Hans"]
    assert wait_until(lambda: not bar.isVisible())
    window.stop_listening()


def test_ac11_a_pair_member_at_the_minimum_probability_is_routed(window, spies) -> None:  # noqa: F811
    start(window)
    submit(window, spies, transcript("Guten Tag", "de", 0.70))

    assert wait_until(lambda: len(window.history) == 1)
    assert not window.held_turn_bar.isVisible()
    assert window.history[0].source_language == DE
    window.stop_listening()


def test_ac11_discard_produces_no_result_and_no_export_line(window, spies, tmp_path) -> None:  # noqa: F811
    start(window)
    submit(window, spies, transcript("Guten Tag", "de"))
    assert wait_until(lambda: len(window.history) == 1)
    submit(window, spies, transcript("Unclear words", "en"))
    assert wait_until(window.held_turn_bar.isVisible)

    click(window.held_turn_bar.discard_button)

    assert not window.held_turn_bar.isVisible()
    assert window.pipeline.held_turns() == ()  # retained audio released
    window.stop_listening()
    assert len(window.history) == 1
    path = tmp_path / "transcript.txt"
    window.write_transcript(path)
    exported = path.read_text(encoding="utf-8")
    assert "Unclear words" not in exported
    assert exported.count(" -> ") == 1


def test_held_turn_bar_keyboard_resolution_excerpt_counter_and_resolving_state(
    window,
    spies,  # noqa: F811
) -> None:
    from PySide6.QtCore import Qt

    start(window)
    long_text = "word " * 50
    submit(window, spies, transcript(long_text, "en"))
    bar = window.held_turn_bar
    assert wait_until(bar.isVisible)
    submit(window, spies, transcript("Second unclear turn", "en"))
    assert wait_until(lambda: bar.counter_label.isVisible())

    assert bar.counter_label.text() == "1 of 2"
    shown = bar.excerpt.strip("“”")
    assert len(shown) == 120 and shown.endswith("…")
    assert bar.transcript_label.toolTip() == long_text

    # Tab order: Translate as German -> Translate as Mandarin (Simplified) -> Discard.
    german, mandarin = bar.translate_buttons[DE], bar.translate_buttons[ZH]
    assert german.nextInFocusChain() is mandarin
    assert mandarin.nextInFocusChain() is bar.discard_button

    # Resolving: the re-recognition blocks; the buttons stay disabled until it reports back.
    release = threading.Event()
    recognizer = spies.recognizer
    transcribe = recognizer.transcribe

    def gated(samples, sample_rate, language=None):
        if language is not None:
            assert release.wait(timeout=5.0)
        return transcribe(samples, sample_rate, language)

    recognizer.transcribe = gated
    recognizer.results.append(transcript("Wort", "de"))
    german.setFocus()
    press(german, Qt.Key.Key_Space)
    assert bar.resolving
    assert not any(button.isEnabled() for button in (german, mandarin, bar.discard_button))
    release.set()

    assert wait_until(lambda: len(window.history) == 1)
    assert wait_until(lambda: not bar.resolving)
    assert bar.isVisible() and not bar.counter_label.isVisible()  # the second turn remains
    assert bar.excerpt == "“Second unclear turn”"
    assert german.isEnabled()
    window.stop_listening()


# AC-22 ------------------------------------------------------------------------------------


def test_ac22_later_turns_flow_while_held_and_stop_discards_the_unresolved_turn(
    window,
    spies,  # noqa: F811
    tmp_path,
) -> None:
    start(window)
    submit(window, spies, transcript("Hello there", "en"))  # T1, held
    assert wait_until(window.held_turn_bar.isVisible)
    submit(window, spies, transcript("Guten Tag", "de"))  # T2
    assert wait_until(lambda: len(window.history) == 1)
    submit(window, spies, transcript("你好", "zh-Hans"))  # T3
    assert wait_until(lambda: len(window.history) == 2)
    assert window.held_turn_bar.isVisible()  # T2 and T3 did not wait for T1

    spies.recognizer.results.append(transcript("Hallo da", "de"))
    click(window.held_turn_bar.translate_buttons[DE])
    assert wait_until(lambda: len(window.history) == 3)

    # On screen T1 is appended after T3; the export orders T1, T2, T3 by capture time.
    assert blocks(window.source_text) == [
        "German: Guten Tag",
        "Mandarin (Simplified): 你好",
        "German: Hallo da",
    ]
    window.stop_listening()
    path = tmp_path / "first-run.txt"
    window.write_transcript(path)
    exported = path.read_text(encoding="utf-8").splitlines()
    turn_lines = [line for line in exported if ": " in line and not line.startswith("#")]
    assert turn_lines == [
        "de: Hallo da",
        "zh-Hans: [de>zh-Hans] Hallo da",
        "de: Guten Tag",
        "zh-Hans: [de>zh-Hans] Guten Tag",
        "zh-Hans: 你好",
        "de: [zh-Hans>de] 你好",
    ]

    # Second run: T1 is still held when the user clicks Stop.
    start(window)
    submit(window, spies, transcript("Still unclear", "en"))
    assert wait_until(window.held_turn_bar.isVisible)

    click(window.stop_button)

    assert not window.held_turn_bar.isVisible()
    assert window.pipeline.held_turns() == ()  # its retained audio is released
    assert len(window.history) == 3
    assert window.statusBar().currentMessage() == (
        "Capture stopped; 1 turn(s) with an unclear language were discarded"
    )
    second = tmp_path / "second-run.txt"
    window.write_transcript(second)
    assert "Still unclear" not in second.read_text(encoding="utf-8")


def test_a_resolution_still_running_at_stop_leaves_no_result(window, spies) -> None:  # noqa: F811
    """W2-F1 through the UI: Stop during a held-turn resolution drops the resolution."""
    start(window)
    submit(window, spies, transcript("Hello there", "en"))
    assert wait_until(window.held_turn_bar.isVisible)
    entered, release = threading.Event(), threading.Event()
    recognizer = spies.recognizer
    transcribe = recognizer.transcribe

    def gated(samples, sample_rate, language=None):
        entered.set()
        assert release.wait(timeout=5.0)
        return transcribe(samples, sample_rate, language)

    recognizer.transcribe = gated
    recognizer.results.append(transcript("Hallo da", "de"))
    click(window.held_turn_bar.translate_buttons[DE])
    assert entered.wait(timeout=2.0)

    click(window.stop_button)
    assert not window.held_turn_bar.isVisible()
    release.set()

    assert wait_until(lambda: not window.held_turn_bar.resolving)
    assert window.history == []
    assert spies.translator.calls == []
    assert not window.held_turn_bar.isVisible()


# VoR-01 / E-03 / E-04 ---------------------------------------------------------------------


def test_vor01_automatic_german_turn_is_labelled_and_exported_with_language_ids(
    window,
    spies,  # noqa: F811
    tmp_path,
    monkeypatch,
) -> None:
    from PySide6.QtWidgets import QFileDialog, QPushButton

    assert window.mode_combo.currentText() == AUTOMATIC
    start(window)
    submit(window, spies, transcript("Guten Morgen, das ist ein Test.", "de"))
    assert wait_until(lambda: len(window.history) == 1)
    assert window.latency_label.text().startswith(DE_TO_ZH + " · ")
    assert window.target_text.toPlainText().startswith("Mandarin (Simplified): ")
    click(window.stop_button)

    path = tmp_path / "transcript-E04.txt"
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", staticmethod(lambda *_args: (str(path), "Text (*.txt)"))
    )
    export = next(b for b in window.findChildren(QPushButton) if b.text() == "Export transcript")
    click(export)

    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[:2] == ["# lianiq transcript v2", "# pair: de zh-Hans"]
    assert lines[2].endswith("] de -> zh-Hans")
    assert window.statusBar().currentMessage() == f"Transcript saved: {path}"
