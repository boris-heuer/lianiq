"""Voice controls, per-call voice options and the bound voice (CAP-0167 contract.md §1-§3).

Unit halves of AC-14 (the controls descriptor per engine), AC-15 (options reach the engine on
the next synthesis without a model reload) and AC-26 (Piper reads its speaker count without
loading a model; sherpa-onnx knows it only after ``load_controls``).
"""

from __future__ import annotations

import json
import sys
import types
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pytest

from lianiq.languages import LanguageId
from lianiq.tts.piper_engine import PiperEngine
from lianiq.tts.sherpa_onnx_engine import SherpaOnnxEngine, SherpaVoiceSettings
from lianiq.tts.voice_controls import RATE_RANGE, VOLUME_RANGE, VoiceControls, VoiceOptions
from lianiq.tts.voice_router import BoundVoice, VoiceRouter
from tests.test_sherpa_onnx_engine import FakeSherpa, voice_dir

DE = LanguageId("de")
ZH = LanguageId("zh-Hans")


@dataclass
class SynthesisConfig18:
    """The fields of ``piper.SynthesisConfig`` in the locked ``piper-tts==1.8.0`` wheel."""

    speaker_id: int | None = None
    length_scale: float | None = None
    noise_scale: float | None = None
    noise_w_scale: float | None = None
    normalize_audio: bool = True
    volume: float = 1.0


@dataclass
class SynthesisConfigNoVolume:
    speaker_id: int | None = None
    length_scale: float | None = None


class FakePiper:
    """A fake ``piper`` module: counts model loads and records each ``syn_config``."""

    def __init__(self, config_type: type | None = SynthesisConfig18) -> None:
        self.loads: list[str] = []
        self.configs: list[object] = []
        self.config_type = config_type

    def module(self) -> types.ModuleType:
        fake = self
        module = types.ModuleType("piper")

        class Voice:
            def synthesize_wav(self, text, wav_file, syn_config=None) -> None:
                fake.configs.append(syn_config)
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(22_050)
                wav_file.writeframes(np.zeros(4, dtype="<i2").tobytes())

        class PiperVoice:
            @staticmethod
            def load(path: str, use_cuda: bool = False) -> Voice:
                fake.loads.append(path)
                return Voice()

        module.PiperVoice = PiperVoice
        if self.config_type is not None:
            module.SynthesisConfig = self.config_type
        return module


def piper_voice(root: Path, metadata: dict | None = None) -> Path:
    voice = root / "de.onnx"
    voice.write_bytes(b"model")
    Path(f"{voice}.json").write_text(json.dumps(metadata or {}), encoding="utf-8")
    return voice


@pytest.fixture
def piper(monkeypatch) -> FakePiper:
    fake = FakePiper()
    monkeypatch.setitem(sys.modules, "piper", fake.module())
    return fake


@pytest.fixture
def sherpa(monkeypatch) -> FakeSherpa:
    fake = FakeSherpa()
    monkeypatch.setitem(sys.modules, "sherpa_onnx", fake.module())
    return fake


# --- §1 VoiceOptions -------------------------------------------------------------------------


def test_default_options_and_ranges() -> None:
    assert VoiceOptions() == VoiceOptions(speaker=None, rate=1.0, volume=1.0)
    assert (RATE_RANGE, VOLUME_RANGE) == ((0.75, 1.5), (0.1, 1.0))
    VoiceOptions(speaker=0, rate=0.75, volume=0.1)
    VoiceOptions(speaker=7, rate=1.5, volume=1.0)


@pytest.mark.parametrize(
    "values",
    [
        {"speaker": -1},
        {"speaker": True},
        {"speaker": 1.0},
        {"rate": 0.7},
        {"rate": 1.55},
        {"rate": float("nan")},
        {"rate": "1.0"},
        {"rate": True},
        {"volume": 0.05},
        {"volume": 1.01},
        {"volume": None},
    ],
)
def test_options_outside_the_ranges_are_rejected(values: dict) -> None:
    with pytest.raises(ValueError):
        VoiceOptions(**values)


# --- §2 Piper --------------------------------------------------------------------------------


def test_ac26_piper_controls_read_the_speaker_count_without_loading_a_model(
    piper, tmp_path
) -> None:
    single = PiperEngine({DE: piper_voice(tmp_path)}, device="cpu")
    assert single.controls(DE) == VoiceControls(speakers=1, rate=True, volume=True)

    multi_root = tmp_path / "multi"
    multi_root.mkdir()
    multi = PiperEngine({DE: piper_voice(multi_root, {"num_speakers": 4})}, device="cpu")
    assert multi.controls(DE) == VoiceControls(speakers=4, rate=True, volume=True)
    assert piper.loads == []


def test_ac14_piper_volume_follows_the_synthesis_config_fields(monkeypatch, tmp_path) -> None:
    voice = piper_voice(tmp_path)
    for config_type, volume in ((SynthesisConfigNoVolume, False), (None, False)):
        monkeypatch.setitem(sys.modules, "piper", FakePiper(config_type).module())
        controls = PiperEngine({DE: voice}, device="cpu").controls(DE)
        assert controls == VoiceControls(speakers=1, rate=True, volume=volume)


def test_ac15_piper_passes_the_options_per_call_without_a_reload(piper, tmp_path) -> None:
    engine = PiperEngine(
        {DE: piper_voice(tmp_path, {"num_speakers": 3})}, length_scale=1.2, device="cpu"
    )

    engine.synthesize_pcm("Hallo", DE)
    engine.synthesize_pcm("Hallo", DE, VoiceOptions(speaker=0, rate=1.5, volume=0.5))
    engine.synthesize("Hallo", DE, VoiceOptions(speaker=2, rate=0.75)).unlink()

    assert piper.configs == [
        SynthesisConfig18(speaker_id=None, length_scale=1.2, volume=1.0),
        SynthesisConfig18(speaker_id=0, length_scale=pytest.approx(0.8), volume=0.5),
        SynthesisConfig18(speaker_id=2, length_scale=pytest.approx(1.6), volume=1.0),
    ]
    assert len(piper.loads) == 1


def test_piper_passes_only_the_fields_the_config_class_has(monkeypatch, tmp_path) -> None:
    fake = FakePiper(SynthesisConfigNoVolume)
    monkeypatch.setitem(sys.modules, "piper", fake.module())
    engine = PiperEngine({DE: piper_voice(tmp_path)}, device="cpu")

    engine.synthesize_pcm("Hallo", DE, VoiceOptions(rate=1.25, volume=0.5))

    assert fake.configs == [SynthesisConfigNoVolume(speaker_id=None, length_scale=0.8)]


def test_piper_speaker_beyond_the_voice_is_rejected(piper, tmp_path) -> None:
    engine = PiperEngine({DE: piper_voice(tmp_path, {"num_speakers": 2})}, device="cpu")

    with pytest.raises(ValueError, match="speaker 2"):
        engine.synthesize_pcm("Hallo", DE, VoiceOptions(speaker=2))


def test_piper_12_path_passes_rate_and_speaker(tmp_path) -> None:
    calls: list[dict] = []

    class OldVoice:
        def synthesize(self, text, wav_file, **kwargs) -> None:
            calls.append(kwargs)
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(16_000)
            wav_file.writeframes(b"\0\0")

    engine = PiperEngine({DE: piper_voice(tmp_path, {"num_speakers": 2})}, device="cpu")
    engine._loaded[DE] = OldVoice()

    engine.synthesize_pcm("Hallo", DE)
    engine.synthesize_pcm("Hallo", DE, VoiceOptions(speaker=1, rate=1.25))

    assert calls == [{"length_scale": 1.0}, {"length_scale": 0.8, "speaker_id": 1}]


# --- §2 sherpa-onnx --------------------------------------------------------------------------


def test_ac14_ac26_sherpa_controls_need_a_loaded_voice(sherpa, tmp_path) -> None:
    engine = SherpaOnnxEngine({ZH: voice_dir(tmp_path)}, {ZH: SherpaVoiceSettings(speaker_id=20)})

    assert engine.controls(ZH) == VoiceControls(speakers=None, rate=True, volume=False)
    assert sherpa.configs == []
    assert engine.load_controls(ZH) == VoiceControls(speakers=174, rate=True, volume=False)
    assert engine.controls(ZH) == VoiceControls(speakers=174, rate=True, volume=False)
    assert len(sherpa.configs) == 1


def test_ac15_sherpa_speaker_zero_is_sid_zero_and_no_model_reload(sherpa, tmp_path) -> None:
    engine = SherpaOnnxEngine({ZH: voice_dir(tmp_path)}, {ZH: SherpaVoiceSettings(speaker_id=20)})

    engine.synthesize_pcm("你好", ZH)
    engine.synthesize_pcm("你好", ZH, VoiceOptions(speaker=0, rate=1.25, volume=0.3))
    engine.synthesize("你好", ZH, VoiceOptions(speaker=31, rate=0.75)).unlink()

    assert sherpa.calls == [("你好", 20, 1.0), ("你好", 0, 1.25), ("你好", 31, 0.75)]
    assert len(sherpa.configs) == 1


def test_sherpa_speaker_beyond_the_voice_is_rejected(sherpa, tmp_path) -> None:
    sherpa.num_speakers = 10
    engine = SherpaOnnxEngine({ZH: voice_dir(tmp_path)})

    with pytest.raises(ValueError, match="speaker 10"):
        engine.synthesize_pcm("你好", ZH, VoiceOptions(speaker=10))
    assert sherpa.calls == []


# --- §3 router and bound voice ---------------------------------------------------------------


def router(piper, sherpa, tmp_path) -> VoiceRouter:
    piper_root = tmp_path / "piper"
    piper_root.mkdir()
    return VoiceRouter(
        {
            DE: PiperEngine({DE: piper_voice(piper_root)}, device="cpu"),
            ZH: SherpaOnnxEngine(
                {ZH: voice_dir(tmp_path)}, {ZH: SherpaVoiceSettings(speaker_id=20)}
            ),
        }
    )


def test_ac14_router_reports_controls_per_language(piper, sherpa, tmp_path) -> None:
    voices = router(piper, sherpa, tmp_path)

    assert voices.controls(DE) == VoiceControls(speakers=1, rate=True, volume=True)
    assert voices.controls(ZH) == VoiceControls(speakers=None, rate=True, volume=False)
    assert (piper.loads, sherpa.configs) == ([], [])
    assert voices.load_controls(ZH).speakers == 174
    assert voices.load_controls(DE).speakers == 1
    assert piper.loads == []


def test_router_controls_of_an_engine_without_controls_offer_nothing() -> None:
    class Plain:
        def synthesize(self, text, language): ...

        def warm_up(self, languages): ...

    voices = VoiceRouter({DE: Plain()})

    assert voices.controls(DE) == VoiceControls(speakers=1, rate=False, volume=False)
    assert voices.load_controls(DE) == voices.controls(DE)


def test_ac15_bound_voice_applies_the_options_of_each_language(piper, sherpa, tmp_path) -> None:
    voices = router(piper, sherpa, tmp_path)
    bound = voices.bound({ZH: VoiceOptions(speaker=0, rate=1.1)})

    assert isinstance(bound, BoundVoice)
    bound.synthesize_pcm("你好", "ZH-hans")
    bound.synthesize("Hallo", DE).unlink()
    voices.bound({DE: VoiceOptions(volume=0.4)}).synthesize_pcm("Hallo", DE)

    assert sherpa.calls == [("你好", 0, 1.1)]
    assert piper.configs == [
        SynthesisConfig18(length_scale=1.0, volume=1.0),
        SynthesisConfig18(length_scale=1.0, volume=0.4),
    ]
    assert (len(piper.loads), len(sherpa.configs)) == (1, 1)  # the router's cached engines


def test_bound_voice_delegates_warm_up_validation_and_device(piper, sherpa, tmp_path) -> None:
    voices = router(piper, sherpa, tmp_path)
    bound = voices.bound({})

    bound.validate_voice_files()
    bound.validate_voice_files((ZH,))
    bound.warm_up((ZH,))

    assert bound.device == voices.device == "cpu"
    assert sherpa.calls == [("普通话（简体）", 20, 1.0)]


def test_bound_voice_writes_a_pcm16_wav(piper, sherpa, tmp_path) -> None:
    output = router(piper, sherpa, tmp_path).bound({}).synthesize("你好", ZH)
    try:
        with wave.open(str(output), "rb") as wav_file:
            assert (wav_file.getnchannels(), wav_file.getsampwidth()) == (1, 2)
    finally:
        output.unlink()
