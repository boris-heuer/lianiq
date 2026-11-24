"""Generate the speech fixtures of the automated PO rows (spec §2.1.4; CAP-0174 AC-03).

Synthetic speech only, with the voices Lianiq ships: Piper ``de_DE-thorsten-medium`` for
German and the sherpa-onnx VITS ``vits-icefall-zh-aishell3`` voice (speaker 0, no noise, as
``lianiq.tts.sherpa_onnx_engine``) for Mandarin. Each fixture is 0.5 s of silence, its
sentences 1 s apart, then 1 s of silence, resampled with the app's own resampler to 16 kHz
mono 16-bit PCM. The WAVs are committed under ``native_e2e/fixtures/`` and pinned by SHA-256
in ``native_e2e/fixtures.py`` (synthesis is not bit-stable across builds, so a rebuilt file
needs a new pin and a new README line).

    python native_e2e/data/make_fixtures.py --models <models folder> [--only NAME ...]

prints one JSON line per fixture (name, SHA-256, frames). Only the models are read.
"""

from __future__ import annotations

import argparse
import json
import sys
import wave
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUT = ROOT / "native_e2e" / "fixtures"
RATE = 16_000
LEAD_S, GAP_S, TAIL_S = 0.5, 1.0, 1.0
PIPER_VOICE = ("piper", "de_DE-thorsten-medium.onnx")
SHERPA_VOICE = ("sherpa", "vits-icefall-zh-aishell3")
# name → (language, sentence) segments
FIXTURES: dict[str, tuple[tuple[str, str], ...]] = {
    "conv_de_16k.wav": (("de", "Guten Morgen, das ist ein Test."),),
    "conv_zh_16k.wav": (("zh", "你好，这是一个测试。"),),
    "listen_de3_16k.wav": (
        ("de", "Guten Morgen."),
        ("de", "Wir liefern die Ware nächste Woche."),
        ("de", "Der Preis enthält die Fracht."),
    ),
    "listen_zh_de_16k.wav": (
        ("zh", "你好，很高兴见到你。"),
        ("de", "Der Preis enthält die Fracht."),
    ),
    "listen_sentinel_16k.wav": (("de", "Lianiq Kontrollsatz QX7 Hörprobe."),),
}

Synth = Callable[[str], tuple[Any, int]]  # text → (float32 mono samples, rate)


def piper_synth(models: Path) -> Synth:
    from piper import PiperVoice

    voice = PiperVoice.load(str(models.joinpath(*PIPER_VOICE)), use_cuda=False)

    def synth(text: str) -> tuple[Any, int]:
        import numpy

        chunks = list(voice.synthesize(text))
        samples = numpy.concatenate([chunk.audio_float_array for chunk in chunks])
        return samples.astype("float32"), int(chunks[0].sample_rate)

    return synth


def sherpa_synth(models: Path) -> Synth:
    import sherpa_onnx

    from lianiq.tts import sherpa_onnx_engine as engine

    folder = models.joinpath(*SHERPA_VOICE)
    config = sherpa_onnx.OfflineTtsConfig(
        model=sherpa_onnx.OfflineTtsModelConfig(
            vits=sherpa_onnx.OfflineTtsVitsModelConfig(
                model=str(folder / engine.MODEL_FILE),
                lexicon=str(folder / engine.LEXICON_FILE),
                tokens=str(folder / engine.TOKENS_FILE),
                noise_scale=engine.NOISE_SCALE,
                noise_scale_w=engine.NOISE_SCALE_W,
                length_scale=1.0,
            ),
            provider="cpu",
            num_threads=1,
        ),
        rule_fsts=",".join(str(folder / name) for name in engine.RULE_FST_FILES),
        rule_fars=str(folder / engine.RULE_FAR_FILE),
        max_num_sentences=1,
    )
    tts = sherpa_onnx.OfflineTts(config)

    def synth(text: str) -> tuple[Any, int]:
        import numpy

        audio = tts.generate(text, sid=0, speed=1.0)
        samples = numpy.asarray(audio.samples, dtype="float32")
        peak = float(numpy.max(numpy.abs(samples))) or 1.0
        return samples * (engine.PEAK_LEVEL / peak), int(audio.sample_rate)

    return synth


def render(segments: tuple[tuple[str, str], ...], voices: dict[str, Synth]) -> bytes:
    """16 kHz mono PCM16 bytes of the segments with the silences of the module docstring."""
    import numpy

    from lianiq.audio.resampler import convert_capture_audio

    parts = [numpy.zeros(int(LEAD_S * RATE), dtype="float32")]
    for position, (language, text) in enumerate(segments):
        if position:
            parts.append(numpy.zeros(int(GAP_S * RATE), dtype="float32"))
        samples, rate = voices[language](text)
        parts.append(convert_capture_audio(samples, rate, RATE))
    parts.append(numpy.zeros(int(TAIL_S * RATE), dtype="float32"))
    pcm = numpy.clip(numpy.concatenate(parts), -1.0, 1.0) * 32767.0
    return pcm.astype("<i2").tobytes()


def write_wav(path: Path, pcm: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(RATE)
        handle.writeframes(pcm)


def make(models: Path, names: list[str], out: Path = OUT) -> list[dict[str, object]]:
    from native_e2e.evidence.sums import file_sha256

    languages = {language for name in names for language, _ in FIXTURES[name]}
    makers = {"de": piper_synth, "zh": sherpa_synth}
    voices = {language: makers[language](models) for language in sorted(languages)}
    results = []
    for name in names:
        pcm = render(FIXTURES[name], voices)
        write_wav(out / name, pcm)
        results.append({"name": name, "sha256": file_sha256(out / name), "frames": len(pcm) // 2})
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate the native-e2e speech fixtures.")
    parser.add_argument("--models", type=Path, required=True, help="models folder (read only)")
    parser.add_argument("--only", nargs="*", choices=sorted(FIXTURES), default=None)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args(argv)
    for result in make(args.models, args.only or sorted(FIXTURES), args.out):
        print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
