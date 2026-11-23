"""Replay, Stop playback, the microphone pause and the failure paths (CAP-0167 WI-04).

The ``qaa``/``qab`` window of ``test_voice_output.py`` with a stoppable fake player: the text
before speech, the paused state line and level, **Replay** with the current options after a
text-only turn, **Stop playback** during synthesis and playback, a synthesis failure notice
and lost speakers (contract.md §4, §7, §8; spec AC-07..AC-09, AC-11..AC-13).
"""

from __future__ import annotations

import os
import threading

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from lianiq.ui import notice_catalog as catalog
from lianiq.ui import strings
from tests._spy_window import spies  # noqa: F401
from tests.languages.synthetic import QAA, QAB
from tests.ui._language_helpers import click, start, submit, transcript, wait_until
from tests.ui.test_voice_output import NAME, open_window, rows  # noqa: F401


class StoppablePlayer:
    """A fake player whose blocking ``play`` ends on ``stop`` (or ``release``)."""

    def __init__(self, window, monkeypatch) -> None:
        from PySide6.QtCore import Qt

        import lianiq.ui.workspaces.conversation as conversation_module

        self.played: list[str] = []
        self.order: list[str] = []  # "result" when the worker emits it, "play" at the player
        window.bridge.result.connect(
            lambda _result: self.order.append("result"), Qt.ConnectionType.DirectConnection
        )
        self.playing, self.released = threading.Event(), threading.Event()
        self.blocking, self.fail = True, False
        window.pipeline.playback = self.play
        monkeypatch.setattr(conversation_module, "stop_playback", self.release)

    def play(self, path, _device) -> None:
        self.order.append("play")
        self.played.append(str(path))
        if self.fail:
            raise OSError("device gone")
        self.playing.set()
        if self.blocking:
            assert self.released.wait(timeout=5.0)

    def release(self) -> None:
        self.released.set()


def gate_synthesis(spies):  # noqa: F811
    """The next syntheses wait for the returned event; ``entered`` is set once one waits."""
    entered, release = threading.Event(), threading.Event()
    synthesize = spies.synthesizer.synthesize

    def gated(text, language, options=None):
        entered.set()
        assert release.wait(timeout=5.0)
        return synthesize(text, language, options)

    spies.synthesizer.synthesize = gated
    return entered, release


@pytest.fixture
def voiced(open_window, monkeypatch):  # noqa: F811
    def make(*voices: str):
        window = open_window(*voices)
        return window, StoppablePlayer(window, monkeypatch)

    return make


def playback_buttons(window):
    return [
        (r.replay_button, r.stop_playback_button)
        for r in (rows(window), window.settings.voice_rows)
    ]


def test_text_first_then_the_microphone_pause_then_replay_with_the_current_options(
    voiced,
    spies,  # noqa: F811
) -> None:
    from lianiq.tts.voice_controls import VoiceOptions

    window, player = voiced(QAB)
    start(window)
    for replay, stop in playback_buttons(window):  # nothing spoken yet (AC-12)
        assert not replay.isEnabled() and replay.toolTip() == strings.VOICE_REPLAY_EMPTY
        assert not stop.isEnabled()

    submit(window, spies, transcript("alpha", QAA))  # into qab: spoken
    assert wait_until(player.playing.is_set)
    assert player.order == ["result", "play"]  # the text is delivered before speech (AC-07)
    assert wait_until(lambda: f"{NAME[QAB]}: " in window.target_text.toPlainText())
    assert wait_until(lambda: window.state_label.text() == strings.VOICE_MIC_PAUSED)
    assert window.capture._muted.is_set() and window.level_bar.value() == 0  # AC-08
    for replay, stop in playback_buttons(window):
        assert stop.isEnabled() and not replay.isEnabled()

    player.release()
    assert wait_until(lambda: window.state_label.text() == "Listening …")
    assert not window.capture._muted.is_set()
    submit(window, spies, transcript("beta", QAB))  # into qaa (no voice): text only
    assert wait_until(lambda: len(window.history) == 2)
    for replay, stop in playback_buttons(window):
        assert replay.isEnabled() and replay.toolTip() == "" and not stop.isEnabled()

    window.conversation.voice_preferences.set_options(QAB, VoiceOptions(rate=1.5))
    player.released.clear()
    player.playing.clear()
    click(rows(window).replay_button)  # AC-11: the earlier qab translation, current options
    assert wait_until(player.playing.is_set)
    assert wait_until(lambda: window.state_label.text() == strings.VOICE_MIC_PAUSED)
    click(window.settings.voice_rows.stop_playback_button)  # the mirror stops it (AC-13)
    assert wait_until(lambda: window.state_label.text() == "Listening …")

    first, again = spies.synthesizer.calls
    assert first == again and first[1] == QAB
    assert spies.synthesizer.options[-1] == VoiceOptions(rate=1.5)
    assert len(player.played) == 2 and window.capture.running


def test_stop_playback_during_synthesis_never_plays_and_the_session_keeps_running(
    voiced,
    spies,  # noqa: F811
) -> None:
    window, player = voiced(QAB)
    start(window)
    entered, release = gate_synthesis(spies)
    submit(window, spies, transcript("alpha", QAA))
    assert wait_until(entered.is_set)
    assert wait_until(rows(window).stop_playback_button.isEnabled)

    click(rows(window).stop_playback_button)  # AC-13
    release.set()

    assert wait_until(lambda: window.state_label.text() == "Listening …")
    assert player.played == [] and window.capture.running
    assert not window.capture._muted.is_set()
    assert not rows(window).stop_playback_button.isEnabled()


def test_a_synthesis_failure_is_a_notice_and_the_next_turn_is_spoken(
    voiced,
    spies,  # noqa: F811
) -> None:
    window, player = voiced(QAB)
    player.blocking = False
    start(window)
    synthesize = spies.synthesizer.synthesize

    def failing(*_args, **_options):
        raise OSError("engine failed")

    spies.synthesizer.synthesize = failing

    submit(window, spies, transcript("alpha", QAA))

    assert wait_until(lambda: window.notices.get(catalog.SYNTHESIS_FAILED_KEY) is not None)
    notice = window.notices.get(catalog.SYNTHESIS_FAILED_KEY)
    assert notice.title == f"Could not speak the translation ({NAME[QAB]})"  # AC-09
    assert len(window.history) == 1 and player.played == []
    assert wait_until(lambda: window.state_label.text() == "Listening …")
    assert not window.capture._muted.is_set()
    spies.synthesizer.synthesize = synthesize
    submit(window, spies, transcript("beta", QAA))
    assert wait_until(lambda: len(player.played) == 1)


def test_lost_speakers_end_spoken_output_and_replay_for_the_session(
    voiced,
    spies,  # noqa: F811
) -> None:
    window, player = voiced(QAB)
    player.fail = True
    start(window)

    submit(window, spies, transcript("alpha", QAA))

    assert wait_until(lambda: window.notices.get(catalog.SPEAKERS_LOST) is not None)
    assert window.pipeline.spoken_languages == frozenset()  # PLAYBACK_FAILED → speakers lost
    assert wait_until(lambda: window.state_label.text() == "Listening …")
    assert not rows(window).replay_button.isEnabled() and window.capture.running
    submit(window, spies, transcript("beta", QAA))
    assert wait_until(lambda: len(window.history) == 2)
    assert len(spies.synthesizer.calls) == 1  # the later turn is text only
    assert window.conversation.voice_preferences.get(QAB).enabled is not False  # switch kept
