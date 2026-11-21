"""CAP-0170 contract §6 stop policy and stale callbacks (AC-11)."""

from __future__ import annotations

import threading

from lianiq.listen.lifecycle import ListenPhase
from lianiq.listen.transcript import SegmentState
from lianiq.ui.shell.session_owner import SessionState
from tests.listen._listen_helpers import GatedTranslator, Harness


class GatedWarmUp:
    def __init__(self) -> None:
        self.release = threading.Event()

    def warm_up(self, subjects) -> None:
        assert self.release.wait(5.0)

    def transcribe(self, *args):
        raise AssertionError("not reached")


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
    controller.start(harness.session)  # a new session while the old turn still runs
    harness.pump(lambda: controller.phase is ListenPhase.LISTENING)
    translator.release.set()
    assert translator.finished.wait(5.0)
    harness.drain(0.3)  # the old worker posts its late result after translate returns
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
