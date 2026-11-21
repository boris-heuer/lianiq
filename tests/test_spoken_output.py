"""Spoken output playback (CAP-0167 WI-02, contract §4/§5): order, stop, failure, replay.

Synthetic languages ``qaa``/``qab`` (AC-24), a fake voice engine and a fake player whose
blocking ``play`` ends when ``stop`` is called. No model, device or display is used.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

import pytest

from lianiq.conversation.spoken_output import (
    PlaybackState,
    SpokenOutput,
)
from lianiq.domain import TranslationResult
from lianiq.languages import (
    InputKind,
    OutputKind,
    RoutingKind,
    SessionPair,
    UsageMode,
)
from lianiq.pipeline import PipelineEventKind, PipelineRunner
from lianiq.tts.voice_controls import VoiceOptions
from lianiq.tts.voice_router import VoiceRouter
from tests._pipeline_helpers import utterance
from tests.languages.synthetic import (
    QAA,
    QAB,
    synthetic_registry,
)

REGISTRY = synthetic_registry()
PAIR = REGISTRY.pair(QAA, QAB)
WAIT = 5.0


def session(routing=RoutingKind.BIDIRECTIONAL, output=OutputKind.TEXT, fixed_source=None):
    mode = UsageMode(InputKind.MICROPHONE, routing, output)
    return SessionPair(PAIR, mode, fixed_source=fixed_source)


# Playback ----------------------------------------------------------------------------------


class FakeEngine:
    """Writes a WAV per call; ``gate`` holds a synthesis until set; ``fail`` raises."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self.calls: list[tuple[str, str, VoiceOptions | None]] = []
        self.gate: threading.Event | None = None
        self.started = threading.Event()
        self.fail = False

    def warm_up(self, languages) -> None:
        pass

    def synthesize(self, text, language, options=None) -> Path:
        self.calls.append((text, language, options))
        self.started.set()
        if self.gate is not None:
            assert self.gate.wait(WAIT)
        if self.fail:
            raise RuntimeError("engine failed")
        path = self.folder / f"{len(self.calls)}.wav"
        path.write_bytes(b"RIFF")
        return path


class FakePlayer:
    """Blocking ``play`` that returns when ``stop`` is called (or at once if not blocking)."""

    def __init__(self, blocking: bool = False) -> None:
        self.blocking = blocking
        self.played: list[tuple[Path, int | None]] = []
        self.playing = threading.Event()
        self.stopped = threading.Event()
        self.order: list[str] | None = None

    def play(self, path: Path, device: int | None) -> None:
        assert path.exists()
        self.played.append((path, device))
        if self.order is not None:
            self.order.append("play")
        self.playing.set()
        if self.blocking:
            assert self.stopped.wait(WAIT)

    def stop(self) -> None:
        self.stopped.set()


class Harness:
    def __init__(self, folder: Path, *, blocking: bool = False) -> None:
        self.engine = FakeEngine(folder)
        self.player = FakePlayer(blocking)
        self.router = VoiceRouter({QAA: self.engine, QAB: self.engine}, REGISTRY)
        self.states: list[PlaybackState] = []
        self.events = []
        self.voice_options = {QAA: VoiceOptions(), QAB: VoiceOptions()}
        self.spoken = SpokenOutput(
            lambda: self.router,
            self.player.play,
            self.player.stop,
            self.voice_options.__getitem__,
            self.states.append,
            self.events.append,
        )
        self.spoken.open(frozenset({QAB}), 7)


def result(target=QAB, text="translated") -> TranslationResult:
    from datetime import datetime
    from uuid import uuid4

    source = PAIR.other(target)
    return TranslationResult(
        turn_id=uuid4(),
        captured_at=datetime.now().astimezone(),
        source_text="source",
        translated_text=text,
        source_language=source,
        target_language=target,
        stt_seconds=0.0,
        translation_seconds=0.0,
    )


def test_speak_synthesizes_with_the_options_plays_and_removes_the_file(tmp_path) -> None:
    harness = Harness(tmp_path)
    harness.voice_options[QAB] = VoiceOptions(rate=1.25)
    turn = result()

    harness.spoken.speak(turn)
    harness.spoken.speak(result(QAA))  # off the plan: shown only (AC-04)

    assert harness.engine.calls == [("translated", QAB, VoiceOptions(rate=1.25))]
    assert [device for _path, device in harness.player.played] == [7]
    assert harness.states == [PlaybackState.SYNTHESIZING, PlaybackState.PLAYING, PlaybackState.IDLE]
    assert harness.spoken.last_spoken is turn
    assert list(tmp_path.iterdir()) == []  # no synthesized audio file remains (AC-23)


class SpeakingPipeline:
    """A runner pipeline whose turns and held-turn resolutions return ``turn``."""

    def __init__(self, spoken: SpokenOutput, turn: TranslationResult) -> None:
        self.spoken = spoken
        self.turn = turn

    def process(self, _item):
        return self.turn

    def resolve(self, _held, _source):
        return self.turn


def test_the_text_is_delivered_before_the_player_starts(tmp_path) -> None:
    harness = Harness(tmp_path)
    order: list[str] = []
    harness.player.order = order
    runner = PipelineRunner(
        SpeakingPipeline(harness.spoken, result()),
        on_result=lambda _r: order.append("result"),
        on_error=pytest.fail,
    )
    runner.start(session())
    runner.submit(utterance())
    runner.stop(timeout=WAIT)
    runner.resolve(object(), QAA).join(WAIT)  # a held turn is delivered the same way

    assert order == ["result", "play", "result", "play"]  # AC-07


def test_stop_during_synthesis_never_plays_it(tmp_path) -> None:
    harness = Harness(tmp_path)
    harness.engine.gate = threading.Event()
    speaking = threading.Thread(target=harness.spoken.speak, args=(result(),))
    speaking.start()
    assert harness.engine.started.wait(WAIT)
    assert harness.spoken.state is PlaybackState.SYNTHESIZING

    harness.spoken.stop_playback()
    harness.engine.gate.set()
    speaking.join(WAIT)

    assert harness.player.played == []
    assert harness.states[-1] is PlaybackState.IDLE
    assert list(tmp_path.iterdir()) == []


def test_stop_during_playback_ends_it_without_a_failure(tmp_path) -> None:
    harness = Harness(tmp_path, blocking=True)
    speaking = threading.Thread(target=harness.spoken.speak, args=(result(),))
    speaking.start()
    assert harness.player.playing.wait(WAIT)

    harness.spoken.stop_playback()
    speaking.join(WAIT)

    assert not speaking.is_alive() and harness.events == []
    assert harness.spoken.state is PlaybackState.IDLE
    assert harness.spoken.plan == {QAB}  # the session keeps speaking (AC-13)
    harness.player.blocking = False
    harness.spoken.speak(result())
    assert len(harness.player.played) == 2


def test_synthesis_failure_keeps_the_text_and_the_next_turn_is_spoken(tmp_path) -> None:
    harness = Harness(tmp_path)
    harness.engine.fail = True
    delivered = []
    runner = PipelineRunner(
        SpeakingPipeline(harness.spoken, result()), on_result=delivered.append, on_error=pytest.fail
    )
    runner.start(session())
    runner.submit(utterance())
    runner.stop(timeout=WAIT)

    assert len(delivered) == 1  # the text stays (AC-09)
    assert [(e.kind, e.language, e.message) for e in harness.events] == [
        (PipelineEventKind.SYNTHESIS_FAILED, QAB, "RuntimeError")
    ]
    assert harness.states[-1] is PlaybackState.IDLE and harness.spoken.plan == {QAB}
    harness.engine.fail = False
    harness.spoken.speak(result())
    assert len(harness.player.played) == 1


def test_replay_resynthesizes_the_last_spoken_turn_with_the_current_options(tmp_path) -> None:
    harness = Harness(tmp_path)
    assert harness.spoken.replay() is None  # nothing to replay yet (AC-12)
    harness.spoken.speak(result(text="first"))
    harness.spoken.speak(result(QAA, text="text only"))
    harness.voice_options[QAB] = VoiceOptions(rate=0.75)

    thread = harness.spoken.replay()
    assert thread is not None and thread.name == "spoken-output-replay" and thread.daemon
    thread.join(WAIT)

    assert harness.engine.calls[-1] == ("first", QAB, VoiceOptions(rate=0.75))  # AC-11
    assert len(harness.player.played) == 2


def test_close_stops_playback_and_queued_turns_finish_as_text(tmp_path) -> None:
    harness = Harness(tmp_path, blocking=True)
    release = threading.Event()
    delivered = []

    class Gated(SpeakingPipeline):
        def process(self, item):
            if delivered:
                assert release.wait(WAIT)
            return self.turn

    runner = PipelineRunner(
        Gated(harness.spoken, result()), on_result=delivered.append, on_error=pytest.fail
    )
    runner.start(session())
    runner.submit(utterance())
    assert harness.player.playing.wait(WAIT)
    runner.submit(utterance())  # queued behind the playing turn

    harness.spoken.close()  # Stop (AC-10): before the runner flushes its queue
    release.set()
    assert runner.stop(timeout=WAIT) == 0

    assert len(delivered) == 2 and len(harness.engine.calls) == 1  # no synthesis after Stop
    assert harness.spoken.last_spoken is None and harness.spoken.replay() is None
    assert harness.states[-1] is PlaybackState.IDLE


def test_logs_name_language_options_and_error_class_only(tmp_path, caplog) -> None:
    harness = Harness(tmp_path)
    caplog.set_level(logging.DEBUG, logger="lianiq.conversation.spoken_output")
    harness.spoken.speak(result(text="secret words"))
    harness.engine.fail = True
    harness.spoken.speak(result(text="secret words"))

    logged = caplog.text
    assert "secret words" not in logged and "engine failed" not in logged
    assert "language=qab" in logged and "RuntimeError" in logged and "rate=1.00" in logged
