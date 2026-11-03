from __future__ import annotations

import sys
import time
import wave
from pathlib import Path

from lianiq.app import build_pipeline
from lianiq.audio.wav import read_pcm16_mono
from lianiq.config import AppConfig
from lianiq.conversation.routing import HeldTurn
from lianiq.languages.modes import InputKind, OutputKind, RoutingKind, SessionPair, UsageMode
from lianiq.languages.registry import LanguageId
from lianiq.pipeline import bind_utterance

MAX_PROCESSING_SECONDS = 3.0


def validate_wav(path: Path, _output_device: int | None) -> None:
    with wave.open(str(path), "rb") as wav_file:
        if wav_file.getnframes() <= 0:
            raise ValueError(f"Synthesized WAV has no frames: {path}")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    config = AppConfig.load()
    config.voice_output = True
    pipeline = build_pipeline(config)
    pipeline.playback = validate_wav
    # Conversation with spoken output needs every model the two fixed cases use.
    session = SessionPair(
        pipeline.registry.pair(*config.languages.pair),
        UsageMode(InputKind.MICROPHONE, RoutingKind.BIDIRECTIONAL, OutputKind.SPOKEN),
    )

    warmup_started = time.perf_counter()
    pipeline.prepare(session)
    synthesizer = pipeline.voice_synthesizer()
    print(f"Warm-up: {time.perf_counter() - warmup_started:.3f} s")
    print(
        "Devices: "
        f"STT={pipeline.recognizer.device}, "
        f"translation={pipeline.translator.device}, "
        f"TTS={synthesizer.device}"
    )

    cases = [
        ("Guten Tag, wie geht es Ihnen?", LanguageId("de")),
        ("您好，您好吗？", LanguageId("zh-Hans")),
    ]
    spoken_fixed = UsageMode(InputKind.MICROPHONE, RoutingKind.FIXED, OutputKind.SPOKEN)
    passed = True
    for source_text, source_language in cases:
        fixed = SessionPair(session.pair, spoken_fixed, fixed_source=source_language)
        label = f"{source_language}>{fixed.fixed_target}"
        source_wav = synthesizer.synthesize(source_text, source_language)
        try:
            utterance = read_pcm16_mono(source_wav)
        finally:
            source_wav.unlink(missing_ok=True)
        result = pipeline.process(bind_utterance(utterance, fixed))
        if result is None or isinstance(result, HeldTurn):
            print(f"FAIL {label}: no speech recognized")
            passed = False
            continue
        case_passed = bool(result.source_text and result.translated_text)
        case_passed = case_passed and result.total_seconds <= MAX_PROCESSING_SECONDS
        passed = passed and case_passed
        marker = "PASS" if case_passed else "FAIL"
        print(
            f"{marker} {label}: {result.total_seconds:.3f} s "
            f"(STT {result.stt_seconds:.3f}, translation {result.translation_seconds:.3f}, "
            f"TTS {result.tts_seconds:.3f})"
        )
        print(f"  recognized: {result.source_text}")
        print(f"  translated: {result.translated_text}")

    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
