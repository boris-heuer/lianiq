"""CAP-0170 contract §6 stop policy and stale callbacks (AC-11)."""

from __future__ import annotations

import threading
import time

import pytest

from lianiq.listen.lifecycle import ListenPhase
from lianiq.listen.transcript import SegmentState
from lianiq.ui.shell.session_owner import SessionState, SessionStillFinishing
from tests.listen._listen_helpers import GatedTranslator, Harness


class GatedWarmUp:
    def __init__(self) -> None:
        self.release = threading.Event()

    def warm_up(self, subjects) -> None:
        assert self.release.wait(5.0)

    def transcribe(self, *args):
        raise AssertionError("not reached")


def ended(harness, timeout: float = 5.0) -> bool:
    """Poll the lingering guard without running the posted callbacks."""
    deadline = time.monotonic() + timeout
    while harness.owner.lingering() is not None:
        if time.monotonic() > deadline:
            return False
        time.sleep(0.01)
    return True


def test_ac11_a_late_result_after_idle_and_after_a_new_start_never_appears(tmp_path) -> None:
    translator = GatedTranslator()
    harness = Harness(tmp_path, translator=translator, flush_seconds=0.05, grace_seconds=0.05)
    controller = harness.controller
    controller.start(harness.session)
    harness.pump(lambda: controller.phase is ListenPhase.LISTENING)
    harness.captures[0].speak()
    harness.pump(lambda: harness.states() == [SegmentState.TRANSLATING])
    controller.stop()
    harness.pump(lambda: controller.phase is ListenPhase.IDLE)
    assert harness.states() == [SegmentState.NOT_FINISHED]
    assert harness.owner.state is SessionState.IDLE
    with pytest.raises(SessionStillFinishing):  # the old turn still runs (AC-05)
        controller.start(harness.session)
    translator.release.set()
    assert translator.finished.wait(5.0)
    assert ended(harness)
    controller.start(harness.session)  # its late result is queued behind this start
    harness.pump(lambda: controller.phase is ListenPhase.LISTENING)
    harness.drain(0.3)
    assert harness.states() == [SegmentState.NOT_FINISHED]
    assert controller.transcript.results() == ()


def test_queued_segments_finish_within_the_flush_bound(tmp_path) -> None:
    translator = GatedTranslator()
    harness = Harness(tmp_path, translator=translator)
    controller = harness.controller
    controller.start(harness.session)
    harness.pump(lambda: controller.phase is ListenPhase.LISTENING)
    harness.captures[0].speak()
    harness.captures[0].speak()
    controller.stop()
    translator.release.set()
    harness.pump(lambda: controller.phase is ListenPhase.IDLE)
    assert harness.states() == [SegmentState.DONE, SegmentState.DONE]


def test_stop_while_loading_opens_nothing(tmp_path) -> None:
    recognizer = GatedWarmUp()
    harness = Harness(tmp_path, recognizer=recognizer)
    controller = harness.controller
    controller.start(harness.session)
    assert controller.phase is ListenPhase.LOADING
    controller.stop()
    assert controller.phase is ListenPhase.STOPPING
    recognizer.release.set()
    harness.pump(lambda: controller.phase is ListenPhase.IDLE)
    assert harness.captures == [] and harness.owner.state is SessionState.IDLE
