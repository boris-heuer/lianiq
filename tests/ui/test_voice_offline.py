"""A spoken Conversation opens no network connection (CAP-0167 AC-21, socket-guarded half).

The ``qaa``/``qab`` window of ``test_voice_output.py`` under the socket guard of
``tests/packs`` (every connect, ``create_connection`` and ``getaddrinfo`` is recorded and
refused): Start, a spoken turn, **Replay**, **Voice options…** with a new rate, a second
spoken turn and Stop. The static half (only Piper and sherpa-onnx) is
``tests/test_tts_engines_static.py``.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from lianiq.tts.voice_controls import VoiceControls
from lianiq.tts.voice_router import NO_CONTROLS
from tests._spy_window import spies  # noqa: F401
from tests.languages.synthetic import QAA, QAB
from tests.packs.conftest import network_attempts  # noqa: F401
from tests.ui._language_helpers import click, start, submit, transcript, wait_until
from tests.ui.test_voice_options import with_controls
from tests.ui.test_voice_output import open_window, rows  # noqa: F401


def test_ac21_speech_replay_and_voice_options_attempt_no_network_connection(
    open_window,  # noqa: F811
    spies,  # noqa: F811
    network_attempts,  # noqa: F811
) -> None:
    window = open_window(QAA, QAB)
    played: list[str] = []
    window.pipeline.playback = lambda path, _device: played.append(str(path))
    with_controls(window, {QAA: NO_CONTROLS, QAB: VoiceControls(1, rate=True, volume=True)})
    start(window)

    submit(window, spies, transcript("alpha", QAA))  # into qab: spoken
    assert wait_until(lambda: len(played) == 1 and rows(window).replay_button.isEnabled())
    click(rows(window).replay_button)
    assert wait_until(lambda: len(played) == 2)
    click(rows(window).options_button(QAB))
    dialog = window.conversation.voice_dialog
    dialog.rate_slider.setValue(130)
    dialog.accept()
    submit(window, spies, transcript("beta", QAA))
    assert wait_until(lambda: len(played) == 3)
    window.stop_listening()

    assert spies.synthesizer.options[-1].rate == 1.3
    assert network_attempts == []
