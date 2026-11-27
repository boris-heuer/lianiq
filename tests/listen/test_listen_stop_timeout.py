"""session-status-truthfulness AC-14 / AC-05: a Listen stop that outlives flush bound plus grace."""

from __future__ import annotations

import threading
import time

import pytest

from lianiq.listen.lifecycle import LISTEN, AlertKind, ListenPhase
from lianiq.listen.transcript import SegmentState
from lianiq.ui.shell.session_owner import SessionState, SessionStillFinishing
from tests._pipeline_helpers import FakeRecognizer
from tests.listen._listen_helpers import GatedTranslator, Harness


class StuckRecognizer(FakeRecognizer):
    """A recognizer spy that never returns until ``release`` is set."""

    def __init__(self) -> None:
        super().__init__(text="Guten Morgen")
        self.release = threading.Event()
        self.entered = threading.Event()

    def transcribe(self, samples, sample_rate, language=None):
        self.entered.set()
        assert self.release.wait(10.0)
        return super().transcribe(samples, sample_rate, language)


def ended(harness, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while harness.owner.lingering() is not None:
        if time.monotonic() > deadline:
            return False
        time.sleep(0.01)
    return True


@pytest.fixture
def stuck(tmp_path):
    recognizer = StuckRecognizer()
    translator = GatedTranslator()
    translator.release.set()
    harness = Harness(
        tmp_path,
        translator=translator,
        recognizer=recognizer,
        flush_seconds=0.05,
        grace_seconds=0.05,
    )
    yield harness, recognizer
    recognizer.release.set()


def test_ac14_a_stuck_recognizer_reports_not_finished_and_lingers(stuck) -> None:
    harness, recognizer = stuck
    controller = harness.controller
    controller.start(harness.session)
    harness.pump(lambda: controller.phase is ListenPhase.LISTENING)
    harness.captures[0].speak()  # in the recognizer, never returns
    assert recognizer.entered.wait(5.0)
    harness.captures[0].speak()  # queued behind it
    controller.stop()
    harness.pump(lambda: controller.phase is ListenPhase.IDLE)

    assert harness.snapshots[-1].not_finished == 2  # one dropped plus the in-flight one
    timeouts = [alert for alert in harness.alerts if alert.kind is AlertKind.STOP_TIMEOUT]
    assert [alert.count for alert in timeouts] == [2]
    assert harness.states() == [SegmentState.NOT_FINISHED, SegmentState.NOT_FINISHED]
    assert harness.owner.state is SessionState.IDLE
    assert harness.owner.lingering() is LISTEN

    with pytest.raises(SessionStillFinishing):  # AC-05: refused, nothing opened
        controller.start(harness.session)
    assert len(harness.captures) == 1 and controller.phase is ListenPhase.IDLE

    recognizer.release.set()
    assert ended(harness)
    controller.start(harness.session)  # the worker exited: Start works with no other action
    harness.pump(lambda: controller.phase is ListenPhase.LISTENING)
    assert len(harness.captures) == 2
    assert controller.transcript.results() == ()  # the late result never appears
    assert harness.snapshots[-1].not_finished == 0


def test_a_stop_within_the_bound_reports_nothing_lost(tmp_path) -> None:
    translator = GatedTranslator()
    harness = Harness(tmp_path, translator=translator)
    controller = harness.controller
    controller.start(harness.session)
    harness.pump(lambda: controller.phase is ListenPhase.LISTENING)
    harness.captures[0].speak()
    controller.stop()
    translator.release.set()
    harness.pump(lambda: controller.phase is ListenPhase.IDLE)
    assert harness.states() == [SegmentState.DONE]
    assert harness.snapshots[-1].not_finished == 0
    assert not [alert for alert in harness.alerts if alert.kind is AlertKind.STOP_TIMEOUT]
    assert harness.owner.lingering() is None
