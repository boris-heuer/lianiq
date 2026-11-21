"""CAP-0172 contract §7: Play translation as an active session (AC-25 to AC-27, AC-29 unit)."""

from __future__ import annotations

import threading
import time

import numpy as np
import pytest

from lianiq.languages import DirectedEdge
from lianiq.text_translation.jobs import FailureReason
from lianiq.text_translation.playback import TextPlayback
from lianiq.text_translation.state import TextResult
from lianiq.ui.shell.session_owner import ActiveSessionOwner, SessionBusy, SessionState
from lianiq.ui.shell.workspaces import WorkspaceId
from tests.text_translation._text_helpers import DE, ZH, GuiThread

RESULT = TextResult(1, 0, DirectedEdge(DE, ZH), "你好。再见。", ("你好。", "再见。"))


class FakeVoice:
    def __init__(self, error: BaseException | None = None) -> None:
        self.calls: list[tuple[str, str]] = []
        self.error = error

    def synthesize_pcm(self, text, language):
        if self.error is not None:
            raise self.error
        self.calls.append((text, language))
        return np.zeros(100, dtype=np.int16), 16_000


class FakePlayer:
    """Plays until ``stop`` (checked every 10 ms) or ``release``; records the device."""

    def __init__(self, error: BaseException | None = None) -> None:
        self.release = threading.Event()
        self.started = threading.Semaphore(0)
        self.devices: list[int | None] = []
        self.error = error

    def play(self, samples, sample_rate, device, stop) -> bool:
        self.devices.append(device)
        self.started.release()
        if self.error is not None:
            raise self.error
        while not self.release.is_set():
            if stop.wait(0.01):
                return False
        return True


class Endpoint:
    runtime_index = 4


class Resolved:
    endpoint = Endpoint()


@pytest.fixture
def gui():
    return GuiThread()


def make(gui, voice=None, player=None, owner=None):
    owner = owner or ActiveSessionOwner()
    voices: list[str] = []
    voice = voice or FakeVoice()

    def bound(language):
        voices.append(language)
        return voice

    playback = TextPlayback(owner, bound, player or FakePlayer(), lambda: Resolved(), gui.post)
    failures: list[FailureReason] = []
    playback.on_failed = failures.append
    return playback, owner, voices, failures


def idle(playback):
    return lambda: playback.state == "idle"


def test_ac23_only_the_target_voice_plays_on_the_conversation_output(gui) -> None:
    player = FakePlayer()
    player.release.set()
    playback, owner, voices, _ = make(gui, player=player)
    playback.play(RESULT)
    assert owner.active is WorkspaceId.TEXT_TRANSLATION
    gui.pump(idle(playback))
    assert voices == [ZH] and player.devices == [4, 4]
    assert playback.played == 1 and owner.state is SessionState.IDLE


@pytest.mark.parametrize("stop", ["button", "f9"])
def test_ac25_ac26_stop_and_f9_end_playback_within_300_ms(gui, stop) -> None:
    player = FakePlayer()
    playback, owner, _, _ = make(gui, player=player)
    playback.play(RESULT)
    assert player.started.acquire(timeout=5)
    gui.pump(lambda: owner.state is SessionState.RUNNING)
    started = time.monotonic()
    playback.stop() if stop == "button" else owner.stop()
    gui.pump(idle(playback))
    assert time.monotonic() - started < 0.3
    assert owner.state is SessionState.IDLE and playback.played == 1


def test_ac27_a_busy_session_refuses_play_before_any_synthesis(gui) -> None:
    owner = ActiveSessionOwner()
    owner.request_start(WorkspaceId.CONVERSATION)
    voice = FakeVoice()
    playback, _, voices, _ = make(gui, voice=voice, owner=owner)
    with pytest.raises(SessionBusy):
        playback.play(RESULT)
    assert voices == [] and voice.calls == [] and playback.state == "idle"


@pytest.mark.parametrize(
    ("voice", "player", "reason"),
    [
        (FakeVoice(RuntimeError("bad speaker")), None, FailureReason.OTHER),
        (None, FakePlayer(OSError("device gone")), FailureReason.DEVICE),
    ],
)
def test_ac29_a_failure_returns_the_owner_to_idle(gui, voice, player, reason) -> None:
    playback, owner, _, failures = make(gui, voice=voice, player=player)
    playback.play(RESULT)
    gui.pump(idle(playback))
    assert failures == [reason] and owner.state is SessionState.IDLE
