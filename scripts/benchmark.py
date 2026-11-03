from __future__ import annotations

import argparse
import time
import wave
from pathlib import Path

import numpy as np

from lianiq.app import build_pipeline
from lianiq.config import AppConfig
from lianiq.conversation.routing import HeldTurn
from lianiq.domain import AudioUtterance
from lianiq.languages.modes import InputKind, OutputKind, RoutingKind, SessionPair, UsageMode
from lianiq.languages.registry import LanguageRegistry
from lianiq.pipeline import bind_utterance


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


def main() -> int:
    parser = argparse.ArgumentParser(description="Measure local end-to-end processing time.")
    parser.add_argument("wav", type=Path)
    parser.add_argument(
        "--source",
        metavar="LANGUAGE_ID",
        help=(
            "Spoken language ID of the WAV, e.g. de or zh-Hans (fixed direction to the other "
            "language of the configured pair). Default: automatic detection within the pair."
        ),
    )
    parser.add_argument("--without-tts", action="store_true")
    args = parser.parse_args()

    config = AppConfig.load()
    if args.without_tts:
        config.voice_output = False
    pipeline = build_pipeline(config)
    session = benchmark_session(pipeline.registry, config, args.source)
    utterance = read_wav(args.wav)
    started = time.perf_counter()
    result = pipeline.process(bind_utterance(utterance, session))
    elapsed = time.perf_counter() - started
    if result is None:
        print("No speech was recognized.")
        return 1
    if isinstance(result, HeldTurn):
        print(f"Language unclear ({result.reason}); the turn was held and not translated.")
        return 1
    print(f"Original:    {result.source_text}")
    print(f"Translation: {result.translated_text}")
    print(f"STT:          {result.stt_seconds:.3f} s")
    print(f"Translation: {result.translation_seconds:.3f} s")
    print(f"TTS+Audio:    {result.tts_seconds:.3f} s")
    print(f"Total:       {elapsed:.3f} s")
    return 0 if elapsed <= 3.0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
