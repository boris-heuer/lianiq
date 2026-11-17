"""In-memory speech synthesis and playback (CAP-0177 WI-03, AC-17: no audio file written).

``synthesize_pcm`` of Piper (both piper-tts API variants) and sherpa-onnx returns the same
PCM16 mono samples the file-based ``synthesize`` writes, without creating any file;
``play_pcm`` plays such a buffer on an explicit endpoint, like ``play_wav`` does a file.
"""

from __future__ import annotations

import sys
import tempfile
import types
import wave

import numpy as np
import pytest

from lianiq.audio.playback import play_pcm
from lianiq.audio.playback_stream import EndpointPlaybackStream
from lianiq.call_bridge.contracts import AudioEndpointRef, EndpointFlow
from lianiq.languages import LanguageId
from lianiq.tts.piper_engine import PiperEngine
from lianiq.tts.sherpa_onnx_engine import SherpaOnnxEngine, SherpaVoiceSettings
from lianiq.tts.voice_router import VoiceRouter
from tests.audio.test_device_opening import fake_sounddevice
from tests.test_sherpa_onnx_engine import FakeSherpa, read_wav, voice_dir

DE = LanguageId("de")
ZH = LanguageId("zh-Hans")
FRAMES = np.array([0, 1200, -3000, 32767, -32768], dtype="<i2")


def no_temp_files(monkeypatch) -> None:
    def refuse(*_args, **_kwargs):
        raise AssertionError("synthesize_pcm must not create a file")

    for name in ("NamedTemporaryFile", "TemporaryFile", "mkstemp"):
        monkeypatch.setattr(tempfile, name, refuse)


class NewApiVoice:
    """piper-tts >= 1.3: ``synthesize_wav`` sets the format and writes the frames."""

    def synthesize_wav(self, text, wav_file, syn_config=None) -> None:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(22_050)
        wav_file.writeframes(FRAMES.tobytes())


class OldApiVoice:
    """piper-tts 1.2: ``synthesize(text, wav_file, length_scale=...)``."""

    def synthesize(self, text, wav_file, length_scale=1.0) -> None:
        NewApiVoice().synthesize_wav(text, wav_file)


@pytest.fixture
def piper_module(monkeypatch):
    module = types.ModuleType("piper")
    module.SynthesisConfig = lambda **kwargs: types.SimpleNamespace(**kwargs)
    monkeypatch.setitem(sys.modules, "piper", module)


@pytest.mark.parametrize("voice", [NewApiVoice(), OldApiVoice()])
def test_piper_synthesize_pcm_matches_the_wav_without_a_file(
    piper_module, voice, tmp_path, monkeypatch
) -> None:
    engine = PiperEngine({DE: tmp_path / "de.onnx"}, device="cpu")
    engine._loaded[DE] = voice
    output = engine.synthesize("Hallo", DE)
    try:
        with wave.open(str(output), "rb") as wav_file:
            expected = wav_file.readframes(wav_file.getnframes())
    finally:
        output.unlink()
    no_temp_files(monkeypatch)

    samples, rate = engine.synthesize_pcm("Hallo", DE)

    assert rate == 22_050 and samples.dtype == np.dtype("<i2")
    assert samples.tobytes() == expected == FRAMES.tobytes()


def test_sherpa_synthesize_pcm_matches_the_wav_without_a_file(monkeypatch, tmp_path) -> None:
    fake = FakeSherpa()
    monkeypatch.setitem(sys.modules, "sherpa_onnx", fake.module())
    engine = SherpaOnnxEngine({ZH: voice_dir(tmp_path)}, {ZH: SherpaVoiceSettings(speaker_id=20)})
    output = engine.synthesize("您好", ZH)
    try:
        channels, width, file_rate, frames = read_wav(output)
    finally:
        output.unlink()
    no_temp_files(monkeypatch)

    samples, rate = engine.synthesize_pcm("您好", ZH)

    assert (channels, width, file_rate) == (1, 2, rate) == (1, 2, 8000)
    assert samples.tolist() == frames.tolist() == [0, 14745, -29490, 5898]


def test_the_router_delegates_in_memory_synthesis_per_language() -> None:
    calls = []

    class Engine:
        def synthesize_pcm(self, text, language):
            calls.append((text, language))
            return FRAMES, 16_000

    router = VoiceRouter({"de": Engine()})
    assert router.synthesize_pcm("Hallo", DE) == (FRAMES, 16_000)
    assert calls == [("Hallo", DE)]


def test_play_pcm_opens_the_index_like_play_wav(monkeypatch) -> None:
    sd = fake_sounddevice(monkeypatch)
    play_pcm(FRAMES, 22_050, 5)
    play_pcm(FRAMES, 22_050, 5, auto_convert=True)
    (data, rate, plain), (_data, _rate, converted) = sd.played
    assert data.tolist() == FRAMES.tolist() and rate == 22_050
    assert plain["device"] == 5 and "extra_settings" not in plain
    assert converted["extra_settings"].auto_convert is True


def test_endpoint_play_pcm_reports_start_and_end_around_the_buffer(monkeypatch) -> None:
    played: list[object] = []
    monkeypatch.setattr(
        "lianiq.audio.playback_stream.play_pcm",
        lambda samples, rate, device: played.append((samples.size, rate, device)),
    )
    endpoint = AudioEndpointRef("id", "Speaker", EndpointFlow.RENDER, "Windows WASAPI", 7)
    stream = EndpointPlaybackStream(endpoint, on_playback_state=played.append)

    stream.play_pcm(FRAMES, 22_050)

    assert played == [True, (5, 22_050, 7), False]
