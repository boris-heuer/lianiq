"""CAP-0172 WI-04: Play translation, Stop, Replay and F9 on the real page (fake voice and player).

AC-05, AC-16 (Play/Replay half), AC-23 to AC-30; real speakers are confirmed in WI-07.
"""

from __future__ import annotations

import pytest

from lianiq.config_voice import VoicePreferences
from lianiq.tts.voice_controls import VoiceOptions
from lianiq.ui import strings
from lianiq.ui.notice_catalog_base import PLAYBACK_FAILED, busy_key
from lianiq.ui.shell.session_owner import SessionState
from lianiq.ui.shell.workspaces import WorkspaceId
from tests._spy_window import ZH, build_window, spies  # noqa: F401 - pytest fixture
from tests.text_translation.test_text_playback import FakePlayer, FakeVoice
from tests.ui._language_helpers import wait_until

TEXT = WorkspaceId.TEXT_TRANSLATION


@pytest.fixture
def player():
    player = FakePlayer()
    yield player
    player.release.set()


@pytest.fixture
def page(tmp_path, spies, monkeypatch, player):  # noqa: F811 - the spies fixture
    window = build_window(tmp_path, monkeypatch)
    window.navigation.select(TEXT)
    workspace = window.text_translation
    workspace.voice = FakeVoice()
    workspace.bound_options: list[dict] = []

    class Router:  # records the options bound per Play (AC-23)
        def bound(self, options):
            workspace.bound_options.append(dict(options))
            return workspace.voice

    monkeypatch.setattr(window.pipeline, "voice_synthesizer", lambda: Router())
    workspace.playback.player = player
    yield workspace
    window.close()


def translated(workspace, text: str = "Hallo. Welt.") -> None:
    workspace.source_edit.setFocus()
    workspace.source_edit.insertPlainText(text)
    workspace.translate_button.click()
    assert wait_until(lambda: workspace.controller.draft.current_result() is not None)


def playing(workspace):
    return lambda: workspace.playback.state == "playing"


def idle(workspace):
    return lambda: workspace.playback.state == "idle"


def test_ac05_ac24_play_needs_a_shown_result_and_never_starts_alone(page, player) -> None:
    assert not page.play_button.isEnabled()
    translated(page)
    assert page.play_button.isEnabled() and page.play_button.text() == strings.TEXT_PLAY
    assert page.voice.calls == [] and player.devices == []  # no synthesis without a click


def test_ac23_play_binds_the_target_voice_options_and_uses_the_output(page, player) -> None:
    VoicePreferences(page.host.config, page.registry).set_options(
        ZH, VoiceOptions(speaker=2, rate=1.25, volume=0.5)
    )
    translated(page)
    page.play_button.click()
    assert wait_until(playing(page))
    assert page.bound_options == [{ZH: VoiceOptions(speaker=2, rate=1.25, volume=0.5)}]
    assert {language for _text, language in page.voice.calls} == {ZH}
    from lianiq.call_bridge.contracts import EndpointFlow

    speakers = page.host.device_setup.resolved(EndpointFlow.RENDER)
    assert player.devices[0] == speakers.endpoint.runtime_index
    assert page.status_label.text() == strings.TEXT_PLAYING


def test_ac25_stop_then_replay_plays_from_the_start(page, player) -> None:
    translated(page)
    page.play_button.click()
    assert wait_until(playing(page))
    assert page.play_button.text() == strings.TEXT_STOP
    page.play_button.click()
    assert wait_until(idle(page))
    assert page.play_button.text() == strings.TEXT_REPLAY
    assert page.result_edit.toPlainText() and page.source_edit.toPlainText() == "Hallo. Welt."
    page.voice.calls.clear()
    page.play_button.click()
    assert wait_until(playing(page))
    first = page.controller.draft.result.segments[0]
    assert page.voice.calls[0] == (first, ZH)  # from the first sentence again


@pytest.mark.parametrize("where", [TEXT, WorkspaceId.SETTINGS])
def test_ac26_f9_stops_playback_from_the_page_and_settings(page, where) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    translated(page)
    page.play_button.click()
    assert wait_until(playing(page))
    page.host.navigation.select(where)
    QTest.keyClick(page.host, Qt.Key.Key_F9)
    assert wait_until(idle(page))
    assert page.host.session_owner.state is SessionState.IDLE
    assert page.source_edit.toPlainText() == "Hallo. Welt."


def test_ac27_one_session_at_a_time_in_both_directions(page) -> None:
    owner = page.host.session_owner
    translated(page)
    generation = owner.request_start(WorkspaceId.CONVERSATION)
    page.play_button.click()
    notice = page.host.notices.get(busy_key(TEXT))
    assert notice is not None and notice.title == "Stop the Conversation session first"
    assert page.voice.calls == []
    owner.mark_idle(generation)
    page.play_button.click()
    assert wait_until(playing(page))
    page.host.start_listening()
    refused = page.host.notices.get(busy_key(WorkspaceId.CONVERSATION))
    assert refused is not None and refused.title == "Stop the Text translation session first"


def test_ac16_ac30_an_edit_stops_playback_and_disables_play(page) -> None:
    translated(page)
    page.play_button.click()
    assert wait_until(playing(page))
    page.source_edit.insertPlainText(" Neu.")
    assert wait_until(idle(page))
    assert not page.play_button.isEnabled() and page.play_button.text() == strings.TEXT_PLAY


def test_ac28_a_missing_target_voice_disables_play(tmp_path, spies, monkeypatch) -> None:  # noqa: F811
    window = build_window(tmp_path, monkeypatch, provisioned=False)
    try:
        window.navigation.select(TEXT)
        workspace = window.text_translation
        translated(workspace)
        assert not workspace.play_button.isEnabled()
        assert (
            workspace.play_hint.text() == "Play translation needs the Mandarin (Simplified) voice."
        )
        assert workspace.result_edit.toPlainText()
    finally:
        window.close()


def test_ac29_a_failing_player_shows_the_notice_and_keeps_the_texts(page, player) -> None:
    player.error = OSError("device gone")
    translated(page)
    page.play_button.click()
    assert wait_until(idle(page))
    notice = page.host.notices.get(PLAYBACK_FAILED)
    assert notice is not None and strings.TEXT_REASON_DEVICE in notice.title
    assert notice.actions[0].label == strings.TEXT_OPEN_AUDIO
    assert page.host.session_owner.state is SessionState.IDLE
    assert page.result_edit.toPlainText() and page.source_edit.toPlainText()
