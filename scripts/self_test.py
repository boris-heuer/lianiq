from __future__ import annotations

import sys
import time
import wave
from pathlib import Path

from lianiq.app import build_pipeline
from lianiq.audio.wav import read_pcm16_mono
from lianiq.config import AppConfig
from lianiq.domain import ConversationMode, Language

MAX_PROCESSING_SECONDS = 3.0

def validate_wav(path: Path, _output_device: int | None) -> None:
    with wave.open(str(path), "rb") as wav_file:
        if wav_file.getnframes() <= 0:
            raise ValueError(f"Synthesized WAV has no frames: {path}")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    config = AppConfig.load()
    config.tts.enabled = True
    pipeline, synthesizer = build_pipeline(config)
    pipeline.playback = validate_wav

    warmup_started = time.perf_counter()
    pipeline.warm_up()
    print(f"Warm-up: {time.perf_counter() - warmup_started:.3f} s")
    print(
        "Devices: "
        f"STT={pipeline.recognizer.device}, "
        f"translation={pipeline.translator.device}, "
        f"TTS={synthesizer.device}"
    )

    cases = [
        ("Guten Tag, wie geht es Ihnen?", Language.GERMAN, ConversationMode.DE_TO_ZH),
        ("您好，您好吗？", Language.MANDARIN, ConversationMode.ZH_TO_DE),
    ]
    passed = True
    for source_text, source_language, mode in cases:
        source_wav = synthesizer.synthesize(source_text, source_language)
        try:
            utterance = read_pcm16_mono(source_wav)
        finally:
            source_wav.unlink(missing_ok=True)
        result = pipeline.process(utterance, mode)
        if result is None:
            print(f"FAIL {mode.value}: no speech recognized")
            passed = False
            continue
        case_passed = bool(result.source_text and result.translated_text)
        case_passed = case_passed and result.total_seconds <= MAX_PROCESSING_SECONDS
        passed = passed and case_passed
        marker = "PASS" if case_passed else "FAIL"
        print(
            f"{marker} {mode.value}: {result.total_seconds:.3f} s "
            f"(STT {result.stt_seconds:.3f}, translation {result.translation_seconds:.3f}, "
            f"TTS {result.tts_seconds:.3f})"
        )
        print(f"  recognized: {result.source_text}")
        print(f"  translated: {result.translated_text}")

    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
