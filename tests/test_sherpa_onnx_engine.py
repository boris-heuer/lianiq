"""sherpa-onnx Mandarin voice backend (CAP-0169 WI-09) against a fake ``sherpa_onnx`` module."""

from __future__ import annotations

import sys
import threading
import types
import wave
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pytest

from lianiq.languages import CapabilityMissingError, LanguageId, RequirementKind
from lianiq.tts.sherpa_onnx_engine import (
    REQUIRED_FILES,
    SherpaOnnxEngine,
    SherpaVoiceSettings,
)
from tests.languages.synthetic import QAA, synthetic_registry

DE = LanguageId("de")
ZH = LanguageId("zh-Hans")


@dataclass
class FakeAudio:
    samples: list[float]
    sample_rate: int = 8000


@dataclass
class FakeSherpa:
    """Records configurations and ``generate`` calls; returns a fixed waveform."""

    samples: list[float] = field(default_factory=lambda: [0.0, 0.25, -0.5, 0.1])
    num_speakers: int = 174
    configs: list = field(default_factory=list)
    calls: list[tuple[str, int, float]] = field(default_factory=list)
    build_delay: float = 0.0
    generate_delay: float = 0.0
    in_flight: int = 0
    max_in_flight: int = 0

    def module(self) -> types.ModuleType:
        fake = self
        module = types.ModuleType("sherpa_onnx")

        def config_type(name: str):
            def build(**kwargs):
                return types.SimpleNamespace(kind=name, **kwargs)

            return build

        module.OfflineTtsVitsModelConfig = config_type("vits")
        module.OfflineTtsModelConfig = config_type("model")
        module.OfflineTtsConfig = config_type("tts")

        class OfflineTts:
            def __init__(self, config) -> None:
                if fake.build_delay:
                    threading.Event().wait(fake.build_delay)
                fake.configs.append(config)
                self.num_speakers = fake.num_speakers
                self.sample_rate = 8000

            def generate(self, text: str, sid: int = 0, speed: float = 1.0) -> FakeAudio:
                fake.in_flight += 1
                fake.max_in_flight = max(fake.max_in_flight, fake.in_flight)
                try:
                    if fake.generate_delay:
                        threading.Event().wait(fake.generate_delay)
                    fake.calls.append((text, sid, speed))
                    return FakeAudio(list(fake.samples))
                finally:
                    fake.in_flight -= 1

        module.OfflineTts = OfflineTts
        return module


@pytest.fixture
def sherpa(monkeypatch) -> FakeSherpa:
    fake = FakeSherpa()
    monkeypatch.setitem(sys.modules, "sherpa_onnx", fake.module())
    return fake


def voice_dir(root: Path, name: str = "voice") -> Path:
    path = root / name
    path.mkdir()
    for file_name in REQUIRED_FILES:
        (path / file_name).write_bytes(b"fixture")
    return path


def read_wav(path: Path) -> tuple[int, int, int, np.ndarray]:
    with wave.open(str(path), "rb") as wav_file:
        frames = np.frombuffer(wav_file.readframes(wav_file.getnframes()), dtype="<i2")
        return wav_file.getnchannels(), wav_file.getsampwidth(), wav_file.getframerate(), frames


def test_synthesize_writes_peak_normalised_pcm16_mono_wav(sherpa, tmp_path) -> None:
    engine = SherpaOnnxEngine(
        {ZH: voice_dir(tmp_path)}, {ZH: SherpaVoiceSettings(speaker_id=20, length_scale=1.15)}
    )

    output = engine.synthesize("您好，您好吗？", ZH)
    try:
        channels, width, rate, frames = read_wav(output)
    finally:
        output.unlink()

    assert (channels, width, rate) == (1, 2, 8000)
    # Peak normalisation to 0.9: the loudest sample (-0.5) becomes -0.9 of full scale.
    assert frames.tolist() == [0, 14745, -29490, 5898]
    assert sherpa.calls == [("您好，您好吗？", 20, 1.0)]


def test_voice_is_configured_deterministic_on_cpu_with_the_rule_files(sherpa, tmp_path) -> None:
    voice = voice_dir(tmp_path)
    engine = SherpaOnnxEngine(
        {ZH: voice},
        {ZH: SherpaVoiceSettings(speaker_id=20, length_scale=1.15)},
        num_threads=4,
        device="cuda",
    )

    engine.warm_up((ZH,))

    assert engine.device == "cpu"  # a requested CUDA device is ignored
    [config] = sherpa.configs
    vits = config.model.vits
    assert (vits.model, vits.lexicon, vits.tokens) == (
        str(voice / "model.onnx"),
        str(voice / "lexicon.txt"),
        str(voice / "tokens.txt"),
    )
    assert (vits.noise_scale, vits.noise_scale_w, vits.length_scale) == (0.0, 0.0, 1.15)
    assert (config.model.provider, config.model.num_threads) == ("cpu", 4)
    rule_fsts = config.rule_fsts.split(",")
    assert [Path(item).name for item in rule_fsts] == [
        "phone.fst",
        "date.fst",
        "number.fst",
        "new_heteronym.fst",
    ]
    assert all(Path(item).is_absolute() for item in rule_fsts)
    assert Path(config.rule_fars) == (voice / "rule.far").resolve()
    assert config.max_num_sentences == 1


def test_warm_up_synthesizes_the_native_name_once_and_caches_the_voice(sherpa, tmp_path) -> None:
    engine = SherpaOnnxEngine({ZH: voice_dir(tmp_path)})

    engine.warm_up((ZH,))
    output = engine.synthesize("你好", ZH)
    output.unlink()

    assert [text for text, _sid, _speed in sherpa.calls] == ["普通话（简体）", "你好"]
    assert len(sherpa.configs) == 1
    assert sherpa.calls[0][1] == 0  # default speaker without settings


def test_concurrent_synthesize_calls_are_serialised_and_load_once(sherpa, tmp_path) -> None:
    # The pipeline thread and the Call Bridge lanes share one engine; sherpa-onnx
    # generate() must never run twice at once, and the voice must be built only once.
    sherpa.build_delay = 0.05
    sherpa.generate_delay = 0.05
    engine = SherpaOnnxEngine({ZH: voice_dir(tmp_path)})
    start = threading.Barrier(4)

    def run() -> Path:
        start.wait(timeout=10)
        return engine.synthesize("你好", ZH)

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(run) for _ in range(4)]
        outputs = [future.result(timeout=10) for future in futures]
    for output in outputs:
        output.unlink()

    assert len(sherpa.calls) == 4
    assert sherpa.max_in_flight == 1
    assert len(sherpa.configs) == 1


def test_unconfigured_voice_raises_capability_missing(sherpa, tmp_path) -> None:
    engine = SherpaOnnxEngine({ZH: voice_dir(tmp_path)})

    for action in (
        lambda: engine.synthesize("Hallo", DE),
        lambda: engine.warm_up((DE,)),
        lambda: engine.validate_voice_files((DE,)),
    ):
        with pytest.raises(CapabilityMissingError) as raised:
            action()
        assert raised.value.requirement.kind is RequirementKind.VOICE
        assert raised.value.requirement.subject == "de"
    assert sherpa.configs == []


def test_missing_voice_files_are_named_before_loading(sherpa, tmp_path) -> None:
    voice = voice_dir(tmp_path)
    (voice / "rule.far").unlink()
    (voice / "tokens.txt").unlink()
    engine = SherpaOnnxEngine({ZH: voice})

    with pytest.raises(FileNotFoundError, match="sherpa-onnx voice artifacts are missing") as err:
        engine.synthesize("你好", ZH)

    assert "tokens.txt" in str(err.value) and "rule.far" in str(err.value)
    assert sherpa.configs == []
    with pytest.raises(FileNotFoundError):
        SherpaOnnxEngine({ZH: tmp_path / "absent"}).validate_voice_files()


def test_speaker_out_of_range_is_rejected(sherpa, tmp_path) -> None:
    sherpa.num_speakers = 10
    engine = SherpaOnnxEngine({ZH: voice_dir(tmp_path)}, {ZH: SherpaVoiceSettings(speaker_id=20)})

    with pytest.raises(ValueError, match="speaker_id 20 is out of range"):
        engine.warm_up((ZH,))


def test_empty_audio_fails_without_leaving_a_file(sherpa, tmp_path, monkeypatch) -> None:
    sherpa.samples = []
    monkeypatch.setattr("tempfile.tempdir", str(tmp_path))
    engine = SherpaOnnxEngine({ZH: voice_dir(tmp_path)})

    with pytest.raises(RuntimeError, match="no audio"):
        engine.synthesize("你好", ZH)

    assert list(tmp_path.glob("lianiq-*.wav")) == []


def test_missing_package_is_reported(tmp_path, monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "sherpa_onnx", None)
    engine = SherpaOnnxEngine({ZH: voice_dir(tmp_path)})

    with pytest.raises(RuntimeError, match="sherpa-onnx is not installed"):
        engine.synthesize("你好", ZH)


def test_voices_use_normalized_ids_and_the_given_registry(sherpa, tmp_path) -> None:
    assert list(SherpaOnnxEngine({"ZH-hans": tmp_path}).voices) == [ZH]

    engine = SherpaOnnxEngine({QAA: voice_dir(tmp_path)}, registry=synthetic_registry())
    engine.warm_up((QAA,))
    assert sherpa.calls[0][0] == "Synthetic A (native)"


@pytest.mark.parametrize(
    "build",
    [
        lambda: SherpaVoiceSettings(speaker_id=-1),
        lambda: SherpaVoiceSettings(length_scale=0),
        lambda: SherpaOnnxEngine({}, num_threads=0),
    ],
)
def test_invalid_settings_are_rejected(build) -> None:
    with pytest.raises(ValueError):
        build()
