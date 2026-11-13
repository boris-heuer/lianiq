"""Generate the N-01 test phrase WAV at image build (CAP-0174, contract section 4.3).

Runs inside the guest during provisioning with the image interpreter, the locked
``piper-tts`` and the German Piper voice from ``scripts/download_models.py``. The WAV is
written to ``C:\\ProgramData\\lianiq-e2e\\test-phrase.wav`` and is never committed: Piper
output is not bit-stable across builds. The script prints one JSON line with the output
path, SHA-256, sample rate and frame count; ``provision.ps1`` records the hash in
``image.json`` and the E-03 row checks the file against it before playing it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import wave
from collections.abc import Callable
from pathlib import Path

PHRASE = "Guten Morgen, das ist ein Test."
DEFAULT_VOICE = Path("models") / "piper" / "de_DE-thorsten-medium.onnx"
DEFAULT_OUTPUT = Path(r"C:\ProgramData\lianiq-e2e\test-phrase.wav")

Synthesizer = Callable[[str, Path, wave.Wave_write], None]


def piper_synthesizer(text: str, voice_path: Path, wav_file: wave.Wave_write) -> None:
    """Synthesize ``text`` with the Piper voice at ``voice_path`` on the CPU."""
    from piper import PiperVoice

    voice = PiperVoice.load(str(voice_path), use_cuda=False)
    voice.synthesize_wav(text, wav_file)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def make_test_phrase(
    voice_path: Path,
    output: Path,
    synthesize: Synthesizer = piper_synthesizer,
) -> dict[str, object]:
    """Write the phrase WAV atomically to ``output`` and describe it.

    Raises ``FileNotFoundError`` when the voice or its ``.json`` metadata is missing and
    ``ValueError`` when the synthesizer produced no audio frames.
    """
    for required in (voice_path, Path(f"{voice_path}.json")):
        if not required.is_file():
            raise FileNotFoundError(f"Piper voice artifact is missing: {required}")
    output.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix="test-phrase-", suffix=".wav", dir=output.parent)
    os.close(handle)
    work = Path(temporary)
    try:
        with wave.open(str(work), "wb") as wav_file:
            synthesize(PHRASE, voice_path, wav_file)
        with wave.open(str(work), "rb") as wav_file:
            frames = wav_file.getnframes()
            rate = wav_file.getframerate()
            channels = wav_file.getnchannels()
        if frames <= 0:
            raise ValueError("Synthesized test phrase has no audio frames")
        work.replace(output)
    except BaseException:
        work.unlink(missing_ok=True)
        raise
    return {
        "path": str(output),
        "sha256": sha256_file(output),
        "sample_rate": rate,
        "channels": channels,
        "frames": frames,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate the N-01 test phrase WAV.")
    parser.add_argument("--voice", type=Path, default=DEFAULT_VOICE, help="Piper .onnx voice")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = make_test_phrase(args.voice, args.output)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Test phrase generation failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
