"""MainWindow session wiring (CAP-0169 WI-04): start gate, bound pair, Stop, export v2.

WI-06 adds the pair control, lock tooltips and held-turn bar
(``test_main_window_languages.py``); these tests drive the controls with pytest-qt style
offscreen clicks over spy adapters.
"""

from __future__ import annotations

import os

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from lianiq.domain import AudioUtterance, Transcript
from lianiq.languages import LanguageId
from tests._spy_window import build_window, spies  # noqa: F401

DE = LanguageId("de")
ZH = LanguageId("zh-Hans")
AUDIO = AudioUtterance(np.zeros(1_600, dtype=np.float32), 16_000)


def wait_until(condition, timeout_ms: int = 3_000) -> bool:
    from PySide6.QtTest import QTest

    waited = 0
    while not condition() and waited < timeout_ms:
        QTest.qWait(10)
        waited += 10
    return condition()


def click(widget) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    QTest.mouseClick(widget, Qt.MouseButton.LeftButton)


@pytest.fixture
def window(tmp_path, spies, monkeypatch):  # noqa: F811
    window = build_window(tmp_path, monkeypatch)
    yield window
    window.close()


@pytest.fixture
def unprovisioned_window(tmp_path, spies, monkeypatch):  # noqa: F811
    window = build_window(tmp_path, monkeypatch, provisioned=False)
    yield window
    window.close()


def test_start_is_refused_and_loads_nothing_when_the_mode_is_unavailable(
    unprovisioned_window,
    spies,  # noqa: F811
) -> None:
    window = unprovisioned_window  # no speech recognition model: no routing is available

    click(window.start_button)
    window.start_listening()  # also refused when invoked directly (F8, diagnostics)

    assert window.statusBar().currentMessage() == (
        "No language pair is ready. Provision languages first (Language readiness)."
    )
    # CAP-0168 WI-03: the refused start is a notice naming the same reason.
    assert window.conversation_notice().title == (
        "No language pair is ready. Provision languages first (Language readiness)."
    )
    assert spies.constructed == []
    assert not window.capture.running
    assert not window.start_button.isEnabled()


def test_routing_is_bound_at_start_and_released_by_stop(window, spies) -> None:  # noqa: F811
    window.mode_combo.setCurrentText("Mandarin (Simplified) → German")
    click(window.start_button)
    assert wait_until(lambda: window.capture.running)

    assert window.session_controller.running
    assert window.session_controller.session.fixed_source == ZH
    assert not window.mode_combo.isEnabled()
    assert not window.swap_button.isEnabled()

    click(window.stop_button)

    assert not window.session_controller.running
    assert window.mode_combo.isEnabled() and window.swap_button.isEnabled()
    click(window.swap_button)
    assert window.current_fixed_source() == DE


def test_turns_show_results_and_export_v2_after_stop(window, spies, tmp_path) -> None:  # noqa: F811
    click(window.start_button)
    assert wait_until(lambda: window.capture.running)
    spies.recognizer.results = [
        Transcript("Guten Tag", DE, 0.95, 0.1, "de"),
        Transcript("Hello", LanguageId("en"), 0.95, 0.1, "en"),
    ]
    window.runner.submit(AUDIO)
    assert wait_until(lambda: len(window.history) == 1)
    window.runner.submit(AUDIO)
    assert wait_until(lambda: window.held_turn_bar.isVisible())
    assert len(window.pipeline.held_turns()) == 1
    assert len(window.history) == 1  # a held turn is never translated

    click(window.stop_button)

    assert window.statusBar().currentMessage() == "Capture stopped"
    assert window.conversation_notice().title == (
        "1 turn(s) with an unclear language were discarded"
    )
    assert window.pipeline.held_turns() == ()
    assert not window.held_turn_bar.isVisible()
    assert window.source_text.toPlainText().strip() == "German: Guten Tag"
    assert window.target_text.toPlainText().strip() == (
        "Mandarin (Simplified): [de>zh-Hans] Guten Tag"
    )
    path = tmp_path / "transcript.txt"
    window.write_transcript(path)
    lines = path.read_text(encoding="utf-8").splitlines()
    turn = window.history[0]
    assert lines == [
        "# lianiq transcript v2",
        "# pair: de zh-Hans",
        f"[{turn.captured_at.isoformat(timespec='seconds')}] de -> zh-Hans",
        "de: Guten Tag",
        "zh-Hans: [de>zh-Hans] Guten Tag",
    ]
