"""Main window held-turn bar (CAP-0169 WI-06; AC-11, VoR-03, E-05, E-06).

Split from ``test_main_window_languages.py``: an offscreen ``MainWindow`` over spy adapters,
driven by its controls; the shared helpers are in ``_language_helpers.py``. These are code
evidence only, not native Windows product evidence (WI-08).
"""

from __future__ import annotations

import os
import threading

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tests._spy_window import spies  # noqa: F401
from tests.ui._language_helpers import (
    DE,
    ZH,
    click,
    language_window,  # noqa: F401
    press,
    start,
    submit,
    transcript,
    wait_until,
)

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
