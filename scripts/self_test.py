from __future__ import annotations

import sys
import time
import wave
from pathlib import Path

from lianiq.app import build_pipeline
from lianiq.audio.playback import stop_playback
from lianiq.audio.wav import read_pcm16_mono
from lianiq.config import AppConfig
from lianiq.conversation.routing import HeldTurn
from lianiq.conversation.spoken_output import SpokenOutput, output_languages
from lianiq.languages.modes import InputKind, OutputKind, RoutingKind, SessionPair, UsageMode
from lianiq.languages.registry import LanguageId
from lianiq.pipeline import PipelineEvent, bind_utterance
from lianiq.tts.voice_controls import VoiceOptions

MAX_PROCESSING_SECONDS = 3.0


def validate_wav(path: Path, _output_device: int | None) -> None:
    with wave.open(str(path), "rb") as wav_file:
        if wav_file.getnframes() <= 0:
            raise ValueError(f"Synthesized WAV has no frames: {path}")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    config = AppConfig.load()
    pipeline = build_pipeline(config)
    # Each translation is spoken after its result, as in Conversation; the WAV is validated
    # instead of played.
    events: list[PipelineEvent] = []
    spoken = SpokenOutput(
        pipeline.voice_synthesizer,
        validate_wav,
        stop_playback,
        lambda _language: VoiceOptions(),
        lambda _state: None,
        events.append,
    )
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
        started = time.perf_counter()
        result = pipeline.process(bind_utterance(utterance, fixed))
        if result is None or isinstance(result, HeldTurn):
            print(f"FAIL {label}: no speech recognized")
            passed = False
            continue
        spoken.open(output_languages(fixed), None)
        tts_started = time.perf_counter()
        spoken.speak(result)
        tts_seconds = time.perf_counter() - tts_started
        total_seconds = time.perf_counter() - started
        case_passed = bool(result.source_text and result.translated_text) and not events
        case_passed = case_passed and total_seconds <= MAX_PROCESSING_SECONDS
        passed = passed and case_passed
        marker = "PASS" if case_passed else "FAIL"
        print(
            f"{marker} {label}: {total_seconds:.3f} s "
            f"(STT {result.stt_seconds:.3f}, translation {result.translation_seconds:.3f}, "
            f"TTS {tts_seconds:.3f})"
        )
        for event in events:
            print(f"  {event.kind.value}: {event.message}")
        events.clear()
        print(f"  recognized: {result.source_text}")
        print(f"  translated: {result.translated_text}")

    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
