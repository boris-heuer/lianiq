"""CAP-0170 contract §6: start, capture binding, queue, stop and device loss (AC-21 and halves)."""

from __future__ import annotations

from pathlib import Path

from lianiq.listen.lifecycle import AlertKind, ListenPhase
from lianiq.listen.transcript import SegmentState
from lianiq.pipeline_types import FailureReason
from lianiq.ui.shell.session_owner import SessionState
from lianiq.ui.shell.workspaces import WorkspaceId
from tests.listen._listen_helpers import GatedTranslator, Harness

LISTEN_SOURCES = Path(__file__).resolve().parents[2] / "lianiq" / "listen"


def started(tmp_path: Path, **kwargs) -> Harness:
    harness = Harness(tmp_path, **kwargs)
    harness.controller.start(harness.session)
    harness.pump(lambda: harness.controller.phase is ListenPhase.LISTENING)
    return harness


def test_a_segment_becomes_a_done_row_and_stop_ends_idle_without_any_voice(tmp_path) -> None:
    translator = GatedTranslator()
    translator.release.set()
    harness = started(tmp_path, translator=translator)
    capture = harness.captures[0]
    assert capture.running and capture.device == 3
    assert harness.owner.state is SessionState.RUNNING
    assert harness.tracker.current.mode is WorkspaceId.LISTEN
    capture.speak()
    harness.pump(lambda: harness.states() == [SegmentState.DONE])
    row = harness.controller.transcript.rows[0]
    assert (row.source_text, row.result.translated_text) == ("Guten Morgen", "早上好")
    assert harness.snapshots[-1].can_export
    harness.controller.stop()
    assert harness.controller.phase is ListenPhase.STOPPING and not capture.running
    harness.pump(lambda: harness.controller.phase is ListenPhase.IDLE)
    assert harness.owner.state is SessionState.IDLE
    assert harness.synthesized == [] and harness.pipeline.spoken is None


def test_overflow_skips_the_oldest_waiting_segment(tmp_path) -> None:
    translator = GatedTranslator()
    harness = started(tmp_path, translator=translator)
    capture = harness.captures[0]
    for _ in range(5):  # one in inference, three queued, then one more
        capture.speak()
    harness.pump(lambda: SegmentState.SKIPPED in harness.states())
    translator.release.set()
    harness.pump(lambda: harness.states().count(SegmentState.DONE) == 4)
    assert harness.states()[1] is SegmentState.SKIPPED


def test_a_failed_turn_is_a_failed_row_with_its_reason(tmp_path) -> None:
    translator = GatedTranslator(error=MemoryError())
    translator.release.set()
    harness = started(tmp_path, translator=translator)
    harness.captures[0].speak()
    harness.pump(lambda: harness.states() == [SegmentState.FAILED])
    assert harness.controller.transcript.rows[0].reason is FailureReason.MEMORY


def test_microphone_loss_stops_then_alerts_with_the_generation(tmp_path) -> None:
    translator = GatedTranslator()
    translator.release.set()
    harness = started(tmp_path, translator=translator)
    harness.captures[0].on_error("device removed")
    harness.pump(lambda: harness.alerts != [])
    assert harness.controller.phase is ListenPhase.IDLE
    alert = harness.alerts[0]
    assert (alert.kind, alert.generation, alert.device_name) == (
        AlertKind.MICROPHONE_LOST,
        harness.owner.generation,
        "Headset",
    )


class FailingWarmUp:
    def __init__(self, error: BaseException) -> None:
        self.error = error

    def warm_up(self, subjects) -> None:
        raise self.error

    def transcribe(self, *args):
        raise AssertionError("not reached")


def test_a_model_load_failure_alerts_and_opens_nothing(tmp_path) -> None:
    harness = Harness(tmp_path, recognizer=FailingWarmUp(FileNotFoundError("model")))
    harness.controller.start(harness.session)
    harness.pump(lambda: harness.alerts != [])
    assert harness.alerts[0].kind is AlertKind.START_FAILED
    assert harness.alerts[0].reason is FailureReason.MODEL
    assert harness.captures == [] and harness.owner.state is SessionState.IDLE


def test_start_is_refused_while_another_mode_holds_the_session(tmp_path) -> None:
    harness = Harness(tmp_path)
    harness.owner.request_start(WorkspaceId.CONVERSATION)
    harness.controller.start(harness.session)
    assert harness.controller.phase is ListenPhase.IDLE
    assert harness.snapshots[-1].readiness.block.value == "busy"


def test_shutdown_stops_at_once(tmp_path) -> None:
    translator = GatedTranslator()
    translator.release.set()
    harness = started(tmp_path, translator=translator)
    harness.controller.shutdown()
    assert harness.controller.phase is ListenPhase.IDLE
    assert harness.owner.state is SessionState.IDLE


def test_ac21_listen_code_never_opens_output_or_writes_audio() -> None:
    forbidden = ("OutputStream", "soundfile", "sf.write", ".wav", "synthesize(", "playback(")
    for path in LISTEN_SOURCES.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert not [word for word in forbidden if word in text], path.name
