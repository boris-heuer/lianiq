"""N-01 test phrase generator of the native-e2e image (CAP-0174 WI-02, contract 4.3).

Piper is replaced by a fake synthesizer: the real voice runs only at image build.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import wave
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "native_e2e" / "data" / "make_test_phrase.py"


def load():
    spec = importlib.util.spec_from_file_location("native_e2e_make_test_phrase", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


phrase = load()


def voice(tmp_path: Path) -> Path:
    model = tmp_path / "de_DE-thorsten-medium.onnx"
    model.write_bytes(b"model")
    Path(f"{model}.json").write_text("{}", encoding="utf-8")
    return model


def fake_synthesizer(frames: int):
    spoken: list[str] = []

    def synthesize(text: str, _voice: Path, wav_file: wave.Wave_write) -> None:
        spoken.append(text)
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(22_050)
        wav_file.writeframes(b"\x01\x00" * frames)

    return synthesize, spoken


def test_the_phrase_is_the_contract_text() -> None:
    assert phrase.PHRASE == "Guten Morgen, das ist ein Test."
    assert phrase.DEFAULT_OUTPUT == Path(r"C:\ProgramData\lianiq-e2e\test-phrase.wav")


def test_the_wav_is_written_and_described_by_its_sha256(tmp_path: Path) -> None:
    synthesize, spoken = fake_synthesizer(2205)
    output = tmp_path / "out" / "test-phrase.wav"

    result = phrase.make_test_phrase(voice(tmp_path), output, synthesize)

    assert spoken == [phrase.PHRASE]
    assert result["sha256"] == hashlib.sha256(output.read_bytes()).hexdigest()
    assert (result["frames"], result["sample_rate"], result["channels"]) == (2205, 22_050, 1)
    assert sorted(path.name for path in output.parent.iterdir()) == ["test-phrase.wav"]
    json.dumps(result)


def test_a_missing_voice_or_empty_audio_leaves_no_file(tmp_path: Path) -> None:
    output = tmp_path / "test-phrase.wav"
    with pytest.raises(FileNotFoundError):
        phrase.make_test_phrase(tmp_path / "missing.onnx", output, fake_synthesizer(1)[0])
    with pytest.raises(ValueError):
        phrase.make_test_phrase(voice(tmp_path), output, fake_synthesizer(0)[0])
    assert not output.exists()
    assert list(tmp_path.glob("test-phrase-*.wav")) == []
