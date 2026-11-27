"""paired-transcript WI-03: per-turn **Replay** in Conversation and Listen (spec §2.2, §3.3).

The ``qaa``/``qab`` Conversation window and the German/Mandarin Listen window over spy
adapters with a stoppable fake player: the row's translation in its target language with the
current options, the microphone pause, **Stop playback**, F9, a Start ending a replay, one
playback at a time, the failure notices and the disabled reasons (AC-05..AC-10, AC-17).
"""
# ruff: noqa: F811 - the imported fixtures

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from lianiq.languages.requirements import DeviceReadiness
from lianiq.listen.lifecycle import ListenPhase
from lianiq.tts.voice_controls import VoiceOptions
from lianiq.ui import notice_catalog as catalog
from lianiq.ui import strings
from lianiq.ui.shell.workspaces import WorkspaceId, session_busy_message
from tests._spy_window import spies  # noqa: F401
from tests.languages.synthetic import QAA, QAB
from tests.ui import _conversation_helpers as conv
from tests.ui._language_helpers import start, submit, transcript, wait_until
from tests.ui._listen_helpers import listen_window, phase_is, speak, states
from tests.ui._listen_helpers import start as start_listen
from tests.ui.test_voice_output import NAME, open_window  # noqa: F401
from tests.ui.test_voice_output_playback import StoppablePlayer, gate_synthesis


@pytest.fixture
def voiced(open_window, monkeypatch):
    def make(*voices: str):
        window = open_window(*voices)
        return window, StoppablePlayer(window, monkeypatch)

    return make


def replay_row(window, row: int, view=None) -> None:
    view = view or conv.view(window)
    view.select_row(row)
    assert view.replay_button.isEnabled(), view.replay_button.toolTip()
    view.replay_button.click()


def two_turns(window, spies, player) -> None:
    """alpha (into qab, spoken and released) and beta (into qaa, no voice)."""
    player.blocking = False
    submit(window, spies, transcript("alpha", QAA))
    assert wait_until(lambda: len(player.played) == 1)
    submit(window, spies, transcript("beta", QAB))
    assert wait_until(lambda: len(window.history) == 2)
    assert wait_until(lambda: window.state_label.text() == "Listening …")
    player.blocking = True


def test_replay_pauses_the_microphone_plays_the_row_and_stop_playback_ends_it(voiced, spies):
    window, player = voiced(QAB)
    start(window)
    two_turns(window, spies, player)
    view, spoken = conv.view(window), window.pipeline.spoken
    last = spoken.last_spoken
    view.select_row(1)  # beta: into qaa, which has no voice (AC-09)
    assert not view.replay_button.isEnabled()
    assert view.replay_button.toolTip() == f"No ready voice for {NAME[QAA]}"
    assert view.copy_translation_button.isEnabled()

    window.conversation.voice_preferences.set_options(QAB, VoiceOptions(rate=1.5))
    replay_row(window, 0)  # AC-05
    assert wait_until(lambda: len(player.played) == 2)
    assert spies.synthesizer.calls[-1][:2] == (window.history[0].translated_text, QAB)
    assert spies.synthesizer.options[-1] == VoiceOptions(rate=1.5)
    assert wait_until(lambda: window.state_label.text() == strings.VOICE_MIC_PAUSED)
    assert window.capture._muted.is_set() and window.level_bar.value() == 0  # AC-06
    assert wait_until(view.stop_playback_button.isEnabled)
    view.select_row(0)
    assert not view.replay_button.isEnabled()  # one playback at a time (AC-08)
    assert spoken.replay_turn(view.current_turn().result, None, print) is None

    view.stop_playback_button.click()  # AC-07
    assert wait_until(lambda: window.state_label.text() == "Listening …")
    assert not window.capture._muted.is_set() and window.capture.running
    assert spoken.last_spoken is last and spoken.plan == {QAB}  # AC-05
    assert wait_until(view.replay_button.isEnabled)
    assert not view.stop_playback_button.isEnabled()


def test_a_spoken_turn_disables_replay_and_waits_for_a_replay(voiced, spies):
    window, player = voiced(QAB)
    start(window)
    submit(window, spies, transcript("alpha", QAA))
    assert wait_until(lambda: len(player.played) == 1)  # the spoken turn plays
    view = conv.view(window)
    view.select_row(0)
    assert wait_until(lambda: not view.replay_button.isEnabled())  # AC-08: on every row
    assert view.replay_button.toolTip() == "" and not view.stop_playback_button.isEnabled()
    player.release()
    assert wait_until(view.replay_button.isEnabled)

    player.released.clear()
    replay_row(window, 0)
    assert wait_until(lambda: len(player.played) == 2)
    submit(window, spies, transcript("gamma", QAA))
    assert wait_until(lambda: len(window.history) == 2)
    assert len(player.played) == 2  # the new turn waits for the replay
    player.release()
    assert wait_until(lambda: len(player.played) == 3)


def test_idle_replay_after_stop_loads_the_voice_on_click_and_a_start_ends_it(voiced, spies):
    window, player = voiced(QAB)
    window.conversation.voice_preferences.set_enabled(QAB, False)  # text only
    window.conversation.refresh_availability()
    player.blocking = False
    start(window)
    submit(window, spies, transcript("alpha", QAA))
    assert wait_until(lambda: len(window.history) == 1)
    window.stop_active_session()  # F9
    assert "synthesizer" not in spies.constructed and player.played == []

    player.blocking = True
    replay_row(window, 0)  # AC-10: an idle page plays; capture stays stopped
    assert wait_until(lambda: len(player.played) == 1)
    assert "synthesizer" in spies.constructed and not window.capture.running
    start(window)  # AC-07: a Start ends the replay first
    assert player.released.is_set()
    assert wait_until(lambda: window.pipeline.spoken.active_replay is None)
    assert window.capture.running


def test_a_stopped_synthesis_is_never_played(voiced, spies):
    window, player = voiced(QAB)
    start(window)
    two_turns(window, spies, player)
    entered, release = gate_synthesis(spies)
    replay_row(window, 0)
    assert wait_until(entered.is_set)
    conv.view(window).stop_playback_button.click()
    release.set()
    assert wait_until(lambda: window.pipeline.spoken.active_replay is None)
    assert len(player.played) == 1  # only the spoken turn (AC-07)


@pytest.mark.parametrize("fail", ["synthesis", "playback"])
def test_a_replay_failure_is_a_notice_and_keeps_the_plan(voiced, spies, fail):
    window, player = voiced(QAB)
    start(window)
    two_turns(window, spies, player)
    if fail == "synthesis":
        spies.synthesizer.synthesize = lambda *_a, **_o: (_ for _ in ()).throw(OSError("x"))
        key = catalog.SYNTHESIS_FAILED_KEY
    else:
        player.fail = True
        key = "conversation.replay-failed"
    replay_row(window, 0)

    assert wait_until(lambda: window.notices.get(key) is not None)
    notice = window.notices.get(key)
    assert notice.workspace is WorkspaceId.CONVERSATION
    assert "alpha" not in f"{notice.title} {notice.detail} {notice.source}"  # AC-17
    assert window.pipeline.spoken.plan == {QAB} and window.pipeline.spoken_languages == {QAB}
    assert window.notices.get(catalog.SPEAKERS_LOST) is None
    assert wait_until(lambda: window.state_label.text() == "Listening …")
    assert len(window.history) == 2 and window.capture.running


def test_replay_is_disabled_while_another_usage_holds_the_session_or_without_speakers(
    voiced, spies, monkeypatch
):
    window, player = voiced(QAB)
    start(window)
    two_turns(window, spies, player)
    window.stop_active_session()
    view = conv.view(window)
    owner = window.session_owner
    generation = owner.request_start(WorkspaceId.MEETING)
    view.select_row(0)
    assert not view.replay_button.isEnabled()  # AC-09
    assert view.replay_button.toolTip() == session_busy_message(WorkspaceId.MEETING)
    owner.mark_idle(generation)
    monkeypatch.setattr(window, "device_readiness", lambda: DeviceReadiness(True, False))
    view.refresh()
    assert view.replay_button.toolTip() == strings.TRANSCRIPT_REPLAY_NO_SPEAKERS
    assert view.copy_pair_button.isEnabled()


@pytest.fixture
def listen(tmp_path, monkeypatch, spies):
    window = listen_window(tmp_path, monkeypatch)
    player = StoppablePlayer(window, monkeypatch)
    yield window, player
    window.listen.shutdown()
    window.close()


def test_listen_replay_mutes_its_capture_shows_the_pause_and_f9_ends_it(listen, spies):
    window, player = listen
    page = window.listen
    start_listen(window)
    speak(window, spies, "Hallo.")
    assert wait_until(lambda: states(window) == ["done"])
    conversation_state = window.state_label.text()

    replay_row(window, 0, page.paired_view)  # VoR-02
    assert wait_until(lambda: len(player.played) == 1)
    capture = window.listen_captures[-1]
    assert wait_until(lambda: page.state_label.text() == strings.VOICE_MIC_PAUSED)
    assert capture.muted and page.level_bar.value() == 0  # AC-06
    page._show_level(0.8)
    assert page.level_bar.value() == 0
    speak(window, spies, "Noch ein Satz.")  # a muted capture delivers nothing
    assert len(states(window)) == 1
    assert window.state_label.text() == conversation_state  # Conversation is not paused
    assert not window.capture._muted.is_set()

    player.release()
    assert wait_until(lambda: page.state_label.text() == strings.LISTEN_STATE_LISTENING)
    assert not capture.muted and capture.running

    player.released.clear()
    replay_row(window, 0, page.paired_view)
    assert wait_until(lambda: len(player.played) == 2)
    window.stop_active_session()  # F9 ends the replay first (AC-07)
    assert player.released.is_set()
    assert phase_is(window, ListenPhase.IDLE)
    assert wait_until(lambda: window.pipeline.spoken.active_replay is None)
    assert not capture.running and len(window.listen_captures) == 1  # no capture restarted
    assert window.pipeline.spoken.last_spoken is None
