from __future__ import annotations

from pathlib import Path

import numpy as np
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

    def fake_synthesize_pcm(text, language):
        calls.append((text, language))
        return np.zeros(1, dtype=np.int16), 22050

    monkeypatch.setattr(engine, "synthesize", fake_synthesize)
    monkeypatch.setattr(engine, "synthesize_pcm", fake_synthesize_pcm)
    return calls


def test_ac17_warm_up_synthesizes_in_memory_and_writes_no_wav(tmp_path, monkeypatch) -> None:
    # A meeting start warms up the voices; AC-17 allows no audio file, not even a temp WAV.
    engine = PiperEngine({ZH: tmp_path / "zh.onnx"}, device="cpu")
    calls: list[tuple[str, str]] = []

    def no_file(text, language):
        raise AssertionError("warm_up must not write a WAV file")

    def in_memory(text, language):
        calls.append((text, language))
        return np.zeros(1, dtype=np.int16), 22050

    monkeypatch.setattr(engine, "synthesize", no_file)
    monkeypatch.setattr(engine, "synthesize_pcm", in_memory)

    engine.warm_up((ZH,))

    assert calls == [("普通话（简体）", ZH)]


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


# --- WI-09: per-language engine selection ------------------------------------------------


def test_build_synthesizer_routes_each_language_to_its_configured_engine(tmp_path) -> None:
    from lianiq.app import build_synthesizer
    from lianiq.config import TtsConfig
    from lianiq.tts.sherpa_onnx_engine import SherpaOnnxEngine

    tts = TtsConfig(device="cpu")  # repository default: de Piper, zh-Hans sherpa-onnx
    router = build_synthesizer(tts, {DE: tmp_path / "de.onnx", ZH: tmp_path / "zh"})

    assert isinstance(router.engines[DE], PiperEngine)
    assert router.engines[DE].voices == {DE: tmp_path / "de.onnx"}
    sherpa = router.engines[ZH]
    assert isinstance(sherpa, SherpaOnnxEngine)
    assert sherpa.voices == {ZH: tmp_path / "zh"}
    assert (sherpa.settings[ZH].speaker_id, sherpa.settings[ZH].length_scale) == (20, 1.15)
    assert sherpa.num_threads == 4
    assert router.device == "cpu"


def test_language_without_engine_entry_uses_piper(tmp_path) -> None:
    from lianiq.app import build_synthesizer
    from lianiq.config import TtsConfig

    router = build_synthesizer(
        TtsConfig(engines={}, device="cpu"), {DE: tmp_path / "de.onnx", ZH: tmp_path / "zh.onnx"}
    )

    assert router.engines[DE] is router.engines[ZH]
    assert isinstance(router.engines[ZH], PiperEngine)


def test_engine_without_a_registry_code_for_the_language_is_rejected(tmp_path) -> None:
    from lianiq.app import build_synthesizer
    from lianiq.config import TtsConfig, VoiceEngineConfig

    tts = TtsConfig(engines={"de": VoiceEngineConfig("sherpa-onnx")})

    with pytest.raises(ValueError, match="'sherpa-onnx' does not support de"):
        build_synthesizer(tts, {DE: tmp_path / "de"})


def test_router_delegates_per_language_and_names_a_missing_voice(tmp_path, monkeypatch) -> None:
    from lianiq.tts.voice_router import VoiceRouter

    de_engine = PiperEngine({DE: tmp_path / "de.onnx"}, device="cpu")
    calls = record_synthesis(de_engine, tmp_path, monkeypatch)
    router = VoiceRouter({DE: de_engine})

    router.warm_up((DE,))
    assert router.synthesize("Hallo", DE) == tmp_path / "de.wav"
    assert calls == [("Deutsch", DE), ("Hallo", DE)]
    with pytest.raises(FileNotFoundError, match="de.onnx"):
        router.validate_voice_files()
    for action in (
        lambda: router.synthesize("你好", ZH),
        lambda: router.warm_up((ZH,)),
        lambda: router.validate_voice_files((ZH,)),
    ):
        with pytest.raises(CapabilityMissingError) as raised:
            action()
        assert raised.value.requirement.subject == "zh-Hans"


# --- CAP-0167: voice controls of the repository default voices ------------------------------


def test_ac14_default_voices_offer_rate_and_volume_or_voice_and_rate(tmp_path, monkeypatch) -> None:
    # German (Piper, single speaker): Rate and, per the 1.8.0 fields, Volume; Mandarin
    # (sherpa-onnx, multi-speaker): Voice once loaded, and Rate, never Volume.
    import sys

    from lianiq.app import build_synthesizer
    from lianiq.config import TtsConfig
    from lianiq.tts.voice_controls import VoiceControls
    from tests.test_sherpa_onnx_engine import FakeSherpa, voice_dir
    from tests.test_voice_controls import FakePiper, piper_voice

    piper, sherpa = FakePiper(), FakeSherpa()
    monkeypatch.setitem(sys.modules, "piper", piper.module())
    monkeypatch.setitem(sys.modules, "sherpa_onnx", sherpa.module())
    router = build_synthesizer(
        TtsConfig(device="cpu"), {DE: piper_voice(tmp_path), ZH: voice_dir(tmp_path)}
    )

    assert router.controls(DE) == VoiceControls(speakers=1, rate=True, volume=True)
    assert router.controls(ZH) == VoiceControls(speakers=None, rate=True, volume=False)
    assert router.load_controls(ZH) == VoiceControls(speakers=174, rate=True, volume=False)
    assert (piper.loads, len(sherpa.configs)) == ([], 1)
