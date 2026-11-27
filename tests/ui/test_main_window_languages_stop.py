"""Main window held turns at Stop and the export journey (CAP-0169 WI-06; AC-22, VoR-01).

CAP-0167 WI-04 adds spoken output at **Stop** (F9) and for a resolved held turn (AC-07, AC-10).

Split from ``test_main_window_languages.py``: an offscreen ``MainWindow`` over spy adapters,
driven by its controls; the shared helpers are in ``_language_helpers.py``. These are code
evidence only, not native Windows product evidence (WI-08).
"""

from __future__ import annotations

import os
import threading

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tests._spy_window import spies  # noqa: F401
from tests.ui import _conversation_helpers as conv
from tests.ui._language_helpers import (
    AUTOMATIC,
    DE,
    DE_TO_ZH,
    click,
    language_window,  # noqa: F401
    start,
    submit,
    transcript,
    wait_until,
)
from tests.ui.test_voice_output_playback import StoppablePlayer, gate_synthesis


def stopped_text(window) -> str:
    """After a session: *Stopped · {n} turns kept*, not *Ready* (session-status-truthfulness)."""
    from lianiq.ui import strings_session

    return strings_session.counted(strings_session.STATE_STOPPED, len(window.history))


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

    # T1 is placed at its capture time, on screen and in the export (paired-transcript AC-01).
    assert conv.originals(window) == [
        "German: Hallo da",
        "German: Guten Tag",
        "Mandarin (Simplified): 你好",
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
    assert wait_until(lambda: not window.conversation.stopping)  # the stop thread (WI-02)

    assert not window.held_turn_bar.isVisible()
    assert window.pipeline.held_turns() == ()  # its retained audio is released
    assert len(window.history) == 3
    # CAP-0168 WI-03: the discarded turn is a warning notice; the status bar shows progress.
    assert window.statusBar().currentMessage() == "Capture stopped"
    assert window.conversation_notice().title == (
        "1 turn(s) with an unclear language were discarded"
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
    assert wait_until(lambda: not window.conversation.stopping)  # the stop thread (WI-02)
    assert not window.held_turn_bar.isVisible()
    release.set()

    assert wait_until(lambda: not window.held_turn_bar.resolving)
    assert window.history == ()
    assert spies.translator.calls == []
    assert not window.held_turn_bar.isVisible()


# VoR-01 / E-03 / E-04 ---------------------------------------------------------------------


def test_vor01_automatic_german_turn_is_labelled_and_exported_with_language_ids(
    window,
    spies,  # noqa: F811
    tmp_path,
    monkeypatch,
) -> None:
    from PySide6.QtWidgets import QFileDialog

    assert window.mode_combo.currentText() == AUTOMATIC
    start(window)
    submit(window, spies, transcript("Guten Morgen, das ist ein Test.", "de"))
    assert wait_until(lambda: len(window.history) == 1)
    assert window.latency_label.text().startswith(DE_TO_ZH + " · ")
    assert conv.translations(window)[0].startswith("Mandarin (Simplified): ")
    click(window.stop_button)

    path = tmp_path / "transcript-E04.txt"
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", staticmethod(lambda *_args: (str(path), "Text (*.txt)"))
    )
    export = window.conversation.export_button  # Listen & translate has one too
    click(export)

    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[:2] == ["# lianiq transcript v2", "# pair: de zh-Hans"]
    assert lines[2].endswith("] de -> zh-Hans")
    assert window.statusBar().currentMessage() == f"Transcript saved: {path}"


# CAP-0167 WI-04: spoken output at Stop and for a resolved held turn ----------------------


def test_a_resolved_held_turn_is_shown_before_it_is_spoken(window, spies, monkeypatch) -> None:  # noqa: F811
    player = StoppablePlayer(window, monkeypatch)
    start(window)
    submit(window, spies, transcript("Hello there", "en"))
    assert wait_until(window.held_turn_bar.isVisible)
    spies.recognizer.results.append(transcript("Hallo da", "de"))

    click(window.held_turn_bar.translate_buttons[DE])

    assert wait_until(player.playing.is_set)
    assert player.order == ["result", "play"]  # AC-07
    player.release()
    assert wait_until(lambda: window.state_label.text() == "Listening …")


def test_stop_during_playback_ends_it_and_clears_replay(window, spies, monkeypatch) -> None:  # noqa: F811
    from lianiq.ui import strings

    player = StoppablePlayer(window, monkeypatch)
    start(window)
    submit(window, spies, transcript("Guten Tag", "de"))
    assert wait_until(player.playing.is_set)

    click(window.stop_button)  # AC-10
    assert wait_until(lambda: not window.conversation.stopping)  # the stop thread (WI-02)

    assert player.released.is_set() and not window.capture.running
    assert window.pipeline.spoken.last_spoken is None
    assert wait_until(lambda: window.conversation.playback_state.value == "idle")
    assert window.state_label.text() == stopped_text(window) and window.level_bar.value() == 0
    replay = window.voice_rows.replay_button
    assert not replay.isEnabled() and replay.toolTip() == strings.VOICE_REPLAY_EMPTY
    assert not window.voice_rows.stop_playback_button.isEnabled()


def test_stop_during_synthesis_never_plays_it(window, spies, monkeypatch) -> None:  # noqa: F811
    player = StoppablePlayer(window, monkeypatch)
    start(window)
    entered, release = gate_synthesis(spies)
    submit(window, spies, transcript("Guten Tag", "de"))
    assert wait_until(entered.is_set)
    threading.Timer(0.2, release.set).start()  # the synthesis ends while Stop waits for it

    click(window.stop_button)  # AC-10
    assert wait_until(lambda: not window.conversation.stopping)  # the stop thread (WI-02)

    assert wait_until(lambda: window.conversation.playback_state.value == "idle")
    assert player.played == [] and window.state_label.text() == stopped_text(window)
    assert not window.capture.running
