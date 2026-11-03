from __future__ import annotations

from pathlib import Path

import pytest

from lianiq.languages import CapabilityMissingError, LanguageId, RequirementKind
from lianiq.tts.piper_engine import PiperEngine
from tests.languages.synthetic import QAA, QAB, synthetic_registry

DE = LanguageId("de")
ZH = LanguageId("zh-Hans")


def record_synthesis(engine: PiperEngine, tmp_path: Path, monkeypatch) -> list[tuple[str, str]]:
    calls: list[tuple[str, str]] = []

    def fake_synthesize(text, language):
        calls.append((text, language))
        output = tmp_path / f"{language}.wav"
        output.touch()
        return output

    monkeypatch.setattr(engine, "synthesize", fake_synthesize)
    return calls


def test_warm_up_runs_real_synthesis_only_for_required_voices(tmp_path, monkeypatch) -> None:
    engine = PiperEngine({DE: tmp_path / "de.onnx", ZH: tmp_path / "zh.onnx"}, device="cpu")
    calls = record_synthesis(engine, tmp_path, monkeypatch)

    engine.warm_up((ZH,))

    # The sample is the language's native name from the registry, synthesized for real.
    assert calls == [("普通话（简体）", ZH)]
    assert not (tmp_path / "zh-Hans.wav").exists()

    engine.warm_up((DE, ZH))
    assert [language for _text, language in calls] == [ZH, DE, ZH]
    assert not (tmp_path / "de.wav").exists()


def test_unconfigured_voice_raises_capability_missing(tmp_path) -> None:
    engine = PiperEngine({DE: tmp_path / "de.onnx"}, device="cpu")

    for action in (
        lambda: engine.synthesize("你好", ZH),
        lambda: engine.warm_up((ZH,)),
        lambda: engine.validate_voice_files((ZH,)),
    ):
        with pytest.raises(CapabilityMissingError) as raised:
            action()
        assert raised.value.requirement.kind is RequirementKind.VOICE
        assert raised.value.requirement.subject == "zh-Hans"


def test_voices_are_keyed_by_normalized_language_id(tmp_path) -> None:
    engine = PiperEngine({"ZH-hans": tmp_path / "zh.onnx"}, device="cpu")

    assert list(engine.voices) == [ZH]


def test_synthetic_voices_use_the_given_registry(tmp_path, monkeypatch) -> None:
    engine = PiperEngine({QAA: tmp_path / "a.onnx"}, device="cpu", registry=synthetic_registry())
    calls = record_synthesis(engine, tmp_path, monkeypatch)

    engine.warm_up((QAA,))

    assert calls == [("Synthetic A (native)", QAA)]
    with pytest.raises(CapabilityMissingError):
        engine.validate_voice_files((QAB,))


def test_call_bridge_voice_preflight_requires_both_voice_and_metadata_pairs(tmp_path) -> None:
    de_voice = tmp_path / "de.onnx"
    zh_voice = tmp_path / "zh.onnx"
    engine = PiperEngine({DE: de_voice, ZH: zh_voice}, device="cpu")
    for path in (de_voice, Path(f"{de_voice}.json"), zh_voice):
        path.touch()

    with pytest.raises(FileNotFoundError, match="zh.onnx.json"):
        engine.validate_voice_files()
    engine.validate_voice_files((DE,))

    Path(f"{zh_voice}.json").touch()
    engine.validate_voice_files()
