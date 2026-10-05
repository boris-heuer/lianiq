from __future__ import annotations

from offline_translator.domain import Language
from offline_translator.tts.piper_engine import PiperEngine


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
