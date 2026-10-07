from __future__ import annotations

from pathlib import Path

import pytest

from lianiq.domain import Language
from lianiq.tts.piper_engine import PiperEngine


def test_warm_up_runs_real_synthesis_for_both_languages(tmp_path, monkeypatch) -> None:
    engine = PiperEngine(tmp_path / "de.onnx", tmp_path / "zh.onnx", device="cpu")
    calls = []

    def fake_synthesize(text, language):
        calls.append((text, language))
        output = tmp_path / f"{language.value}.wav"
        output.touch()
        return output

    monkeypatch.setattr(engine, "synthesize", fake_synthesize)

    engine.warm_up()

    assert [language for _text, language in calls] == [Language.GERMAN, Language.MANDARIN]
    assert not (tmp_path / "de.wav").exists()
    assert not (tmp_path / "zh.wav").exists()


def test_call_bridge_voice_preflight_requires_both_voice_and_metadata_pairs(tmp_path) -> None:
    de_voice = tmp_path / "de.onnx"
    zh_voice = tmp_path / "zh.onnx"
    engine = PiperEngine(de_voice, zh_voice, device="cpu")
    for path in (de_voice, Path(f"{de_voice}.json"), zh_voice):
        path.touch()

    with pytest.raises(FileNotFoundError, match="zh.onnx.json"):
        engine.validate_voice_files()

    Path(f"{zh_voice}.json").touch()
    engine.validate_voice_files()
