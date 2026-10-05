from __future__ import annotations

import sys
import time
import wave
from pathlib import Path

import numpy as np

from offline_translator.app import build_pipeline
from offline_translator.config import AppConfig
from offline_translator.domain import AudioUtterance, ConversationMode, Language

MAX_PROCESSING_SECONDS = 3.0


def read_and_resample(path: Path, target_rate: int = 16_000) -> AudioUtterance:
    with wave.open(str(path), "rb") as wav_file:
        if wav_file.getnchannels() != 1 or wav_file.getsampwidth() != 2:
            raise ValueError(f"Expected mono PCM16 WAV: {path}")
        source_rate = wav_file.getframerate()
        samples = np.frombuffer(wav_file.readframes(wav_file.getnframes()), dtype=np.int16)
    float_samples = samples.astype(np.float32) / 32768.0
    if source_rate != target_rate:
        old_positions = np.arange(len(float_samples), dtype=np.float64)
        new_positions = np.linspace(
            0,
            len(float_samples) - 1,
            round(len(float_samples) * target_rate / source_rate),
        )
        float_samples = np.interp(new_positions, old_positions, float_samples).astype(np.float32)
    return AudioUtterance(float_samples, target_rate)


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
            utterance = read_and_resample(source_wav)
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
