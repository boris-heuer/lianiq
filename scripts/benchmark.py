from __future__ import annotations

import argparse
import statistics
import time
import wave
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

import numpy as np

from lianiq.app import build_pipeline
from lianiq.audio.playback import stop_playback
from lianiq.call_bridge.contracts import AudioEndpointRef, EndpointFlow
from lianiq.config import AppConfig, AudioConfig
from lianiq.conversation.routing import HeldTurn
from lianiq.conversation.spoken_output import SpokenOutput, output_languages
from lianiq.domain import AudioUtterance
from lianiq.languages.modes import (
    MEETING_MODE,
    InputKind,
    OutputKind,
    RoutingKind,
    SessionPair,
    UsageMode,
)
from lianiq.languages.registry import LanguageRegistry
from lianiq.meeting import MeetingEndpoints, MeetingRole, TableInputDuringOutput
from lianiq.meeting.controller import (
    MeetingController,
    MeetingEventKind,
    MeetingOptions,
    SharedEngines,
)
from lianiq.pipeline import bind_utterance
from lianiq.tts.voice_controls import VoiceOptions
from lianiq.ui.shell.session_owner import ActiveSessionOwner

MEETING_TARGET_SECONDS = 4.0  # spec §1.4: median pause-to-text, utterance <= 8 s


def read_wav(path: Path) -> AudioUtterance:
    with wave.open(str(path), "rb") as wav:
        if wav.getnchannels() != 1 or wav.getsampwidth() != 2 or wav.getframerate() != 16_000:
            raise ValueError("Benchmark WAV must be mono, PCM16, and 16 kHz")
        samples = np.frombuffer(wav.readframes(wav.getnframes()), dtype=np.int16)
    return AudioUtterance(samples.astype(np.float32) / 32768.0, 16_000)


def benchmark_session(
    registry: LanguageRegistry, config: AppConfig, source: str | None
) -> SessionPair:
    """Automatic routing within the configured pair, or the fixed direction from ``source``."""
    fixed_source = None if source is None else registry.get(source).id
    return SessionPair(
        registry.pair(*config.languages.pair),
        UsageMode(
            InputKind.MICROPHONE,
            RoutingKind.BIDIRECTIONAL if fixed_source is None else RoutingKind.FIXED,
            OutputKind.SPOKEN if config.voice_output else OutputKind.TEXT,
        ),
        fixed_source=fixed_source,
    )


def meeting_session(registry: LanguageRegistry, config: AppConfig) -> SessionPair:
    """The configured pair as a meeting with ``meeting.local_language`` (CAP-0177)."""
    local = registry.get(config.meeting.local_language).id
    return SessionPair(registry.pair(*config.languages.pair), MEETING_MODE, local_language=local)


class _NullStream:
    """The benchmark feeds the recorded fixtures itself; no device is opened."""

    def __init__(self, **_kwargs) -> None:
        pass

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def close(self) -> None:
        pass


class _SilentPlayback:
    """Speech is synthesised (it is part of the worker's load) but not played."""

    def __init__(self, endpoint: AudioEndpointRef, *, on_playback_state) -> None:
        self.on_playback_state = on_playback_state

    def play_pcm(self, _samples, _sample_rate) -> None:
        self.on_playback_state(True)
        self.on_playback_state(False)


def run_meeting(
    session: SessionPair,
    engines: SharedEngines,
    table_wavs: Sequence[Path],
    user_wavs: Sequence[Path],
    audio: AudioConfig,
    *,
    min_probability: float = 0.7,
    realtime: bool = True,
) -> dict[str, list[float]]:
    """Feed both inputs at once; return the pause-to-text seconds of each line by role.

    The fixtures of both inputs are interleaved block by block (``realtime`` paces them at
    ``audio.chunk_ms``). Latency runs from the end of a contribution (its speech pause) to
    its running-view line, so it includes the wait behind the other input's contribution.
    """
    latencies: dict[str, list[float]] = {role.value: [] for role in MeetingRole}

    def publish(event) -> None:
        if event.kind is MeetingEventKind.LINE:
            elapsed = datetime.now().astimezone() - event.line.ended_at
            latencies[event.role.value].append(elapsed.total_seconds())

    def ref(index: int, flow: EndpointFlow) -> AudioEndpointRef:
        name = f"benchmark-{flow.value}-{index}"
        return AudioEndpointRef(name, name, flow, "benchmark", index, 1, audio.sample_rate)

    endpoints = MeetingEndpoints(
        ref(1, EndpointFlow.CAPTURE), ref(2, EndpointFlow.RENDER), ref(3, EndpointFlow.CAPTURE)
    )
    options = MeetingOptions(False, TableInputDuringOutput.MUTE, 0, 1_000)
    controller = MeetingController(
        session,
        endpoints,
        options,
        engines,
        ActiveSessionOwner(),
        publish,
        audio=audio,
        detection_min_probability=min_probability,
        stream_factory=_NullStream,
        playback_factory=_SilentPlayback,
    )
    block = audio.sample_rate * audio.chunk_ms // 1_000
    pause = np.zeros(block * (audio.end_silence_ms // audio.chunk_ms + 1), dtype=np.float32)

    def blocks(paths: Sequence[Path]) -> list[np.ndarray]:
        samples = [np.concatenate((read_wav(path).samples, pause)) for path in paths]
        joined = np.concatenate(samples) if samples else np.zeros(0, dtype=np.float32)
        return [joined[i : i + block] for i in range(0, joined.size - block + 1, block)]

    inputs = {
        MeetingRole.TABLE_CAPTURE: blocks(table_wavs),
        MeetingRole.USER_CAPTURE: blocks(user_wavs),
    }
    controller.start()
    try:
        for index in range(max(len(items) for items in inputs.values())):
            for role, items in inputs.items():
                if index < len(items):
                    controller.captures[role].process_block(items[index])
            if realtime:
                time.sleep(audio.chunk_ms / 1_000)
    finally:
        controller.stop(timeout=600.0)
    return {role: values for role, values in latencies.items() if values}


def meeting_report(latencies: dict[str, list[float]]) -> tuple[list[str], float | None]:
    every = [value for values in latencies.values() for value in values]
    lines = [
        f"{role}: {len(values)} lines, median {statistics.median(values):.3f} s"
        for role, values in latencies.items()
    ]
    median = statistics.median(every) if every else None
    summary = "no line" if median is None else f"{median:.3f} s over {len(every)} lines"
    lines.append(f"Median pause-to-text: {summary}")
    return lines, median


def main_meeting(args: argparse.Namespace, config: AppConfig) -> int:
    pipeline = build_pipeline(config)
    session = meeting_session(pipeline.registry, config)
    pipeline.prepare(session)
    engines = SharedEngines(
        pipeline.speech_recognizer(), pipeline.text_translator(), pipeline.voice_synthesizer()
    )
    latencies = run_meeting(
        session,
        engines,
        args.meeting_table or (),
        args.meeting_you or (),
        config.audio,
        min_probability=config.languages.detection_min_probability,
    )
    lines, median = meeting_report(latencies)
    print("\n".join(lines))
    if median is None:
        return 1
    return 0 if median <= MEETING_TARGET_SECONDS else 2


def speak(pipeline, session: SessionPair, result) -> float:
    """Speak ``result`` after it was shown, as Conversation does (CAP-0167); its seconds."""
    if session.mode.output is not OutputKind.SPOKEN or pipeline.playback is None:
        return 0.0
    spoken = SpokenOutput(
        pipeline.voice_synthesizer,
        pipeline.playback,
        stop_playback,
        lambda _language: VoiceOptions(),
        lambda _state: None,
        lambda event: print(f"{event.kind.value}: {event.message}"),
    )
    spoken.open(output_languages(session), None)
    started = time.perf_counter()
    spoken.speak(result)
    return time.perf_counter() - started


def main() -> int:
    parser = argparse.ArgumentParser(description="Measure local end-to-end processing time.")
    parser.add_argument("wav", type=Path, nargs="?")
    parser.add_argument(
        "--source",
        metavar="LANGUAGE_ID",
        help=(
            "Spoken language ID of the WAV, e.g. de or zh-Hans (fixed direction to the other "
            "language of the configured pair). Default: automatic detection within the pair."
        ),
    )
    parser.add_argument("--without-tts", action="store_true")
    parser.add_argument(
        "--meeting-table",
        type=Path,
        action="append",
        metavar="WAV",
        help="Meeting run: a recorded table-language fixture for the table input (repeatable).",
    )
    parser.add_argument(
        "--meeting-you",
        type=Path,
        action="append",
        metavar="WAV",
        help="Meeting run: a recorded local-language fixture for your microphone (repeatable).",
    )
    args = parser.parse_args()

    meeting = bool(args.meeting_table or args.meeting_you)
    if args.wav is None and not meeting:
        parser.error("a WAV file or --meeting-table/--meeting-you fixtures are required")
    config = AppConfig.load()
    if meeting:
        return main_meeting(args, config)
    if args.without_tts:
        config.voice_output = False
    pipeline = build_pipeline(config)
    session = benchmark_session(pipeline.registry, config, args.source)
    utterance = read_wav(args.wav)
    started = time.perf_counter()
    result = pipeline.process(bind_utterance(utterance, session))
    if result is None:
        print("No speech was recognized.")
        return 1
    if isinstance(result, HeldTurn):
        print(f"Language unclear ({result.reason}); the turn was held and not translated.")
        return 1
    tts_seconds = speak(pipeline, session, result)
    elapsed = time.perf_counter() - started
    print(f"Original:    {result.source_text}")
    print(f"Translation: {result.translated_text}")
    print(f"STT:          {result.stt_seconds:.3f} s")
    print(f"Translation: {result.translation_seconds:.3f} s")
    print(f"TTS+Audio:    {tts_seconds:.3f} s")
    print(f"Total:       {elapsed:.3f} s")
    return 0 if elapsed <= 3.0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
