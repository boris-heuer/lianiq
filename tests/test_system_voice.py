"""Installed Windows voice first, bundled voice as fallback (lianiq#81)."""

from __future__ import annotations

import io
import wave
from pathlib import Path

import numpy as np

from lianiq.app import build_synthesizer
from lianiq.config import TtsConfig
from lianiq.languages.registry import BUILTIN_REGISTRY
from lianiq.tts.system_voice import SystemVoiceFirst
from lianiq.tts.voice_controls import VoiceControls, VoiceOptions


def _wav(rate: int = 22050, frames: int = 100) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(rate)
        writer.writeframes(np.full(frames, 1000, dtype="<i2").tobytes())
    return buffer.getvalue()


class FakeFallback:
    device = "cpu"
    registry = BUILTIN_REGISTRY

    def __init__(self) -> None:
        self.calls: list[str] = []

    def synthesize_pcm(self, text, language, options=None):
        self.calls.append(f"pcm:{text}")
        return np.zeros(4, dtype="<i2"), 8000

    def synthesize(self, text, language, options=None):
        self.calls.append(f"wav:{text}")
        return Path("fallback.wav")

    def warm_up(self, languages):
        self.calls.append("warm")

    def validate_voice_files(self, languages=None):
        self.calls.append("validate")

    def controls(self, language):
        return VoiceControls(None, rate=True, volume=False)

    def load_controls(self, language):
        return VoiceControls(174, rate=True, volume=False)


def test_without_an_installed_voice_every_call_goes_to_the_bundled_voice() -> None:
    fallback = FakeFallback()
    engine = SystemVoiceFirst(fallback, "zh-CN", find=lambda tag: [])
    assert engine.synthesize_pcm("你好", "zh-Hans")[1] == 8000
    assert engine.synthesize("你好", "zh-Hans") == Path("fallback.wav")
    engine.warm_up(["zh-Hans"])
    engine.validate_voice_files(["zh-Hans"])
    assert engine.load_controls("zh-Hans").speakers == 174
    assert fallback.calls == ["pcm:你好", "wav:你好", "warm", "validate"]
    assert engine.device == "cpu"


def test_an_installed_voice_speaks_with_rate_volume_and_speaker() -> None:
    fallback = FakeFallback()
    rendered: list[tuple[object, str, VoiceOptions]] = []

    def render(voice, text, options):
        rendered.append((voice, text, options))
        return _wav()

    engine = SystemVoiceFirst(
        fallback, "zh-CN", find=lambda tag: ["huihui", "kangkang"], render=render
    )
    pcm, rate = engine.synthesize_pcm(
        "你好", "zh-Hans", VoiceOptions(speaker=1, rate=1.2, volume=0.5)
    )
    assert rate == 22050 and pcm.dtype == np.dtype("<i2") and pcm.size == 100
    assert rendered[-1] == ("kangkang", "你好", VoiceOptions(speaker=1, rate=1.2, volume=0.5))
    engine.synthesize_pcm("你好", "zh-Hans", VoiceOptions(speaker=20))  # saved sherpa speaker
    assert rendered[-1][0] == "huihui"
    path = engine.synthesize("你好", "zh-Hans")
    try:
        with wave.open(str(path)) as reader:
            assert reader.getframerate() == 22050
    finally:
        path.unlink()
    engine.warm_up(["zh-Hans"])
    engine.validate_voice_files(["zh-Hans"])
    assert engine.load_controls("zh-Hans") == VoiceControls(2, rate=True, volume=True)
    assert fallback.calls == []
    assert engine.device == "windows"


def test_the_default_config_puts_the_windows_voice_in_front_of_mandarin_only(tmp_path) -> None:
    voices = {"de": tmp_path / "de.onnx", "zh-Hans": tmp_path / "zh"}
    router = build_synthesizer(TtsConfig(), voices)
    zh = router.engines[BUILTIN_REGISTRY.get("zh-Hans").id]
    assert isinstance(zh, SystemVoiceFirst) and zh.tag == "zh-CN"
    assert not isinstance(router.engines[BUILTIN_REGISTRY.get("de").id], SystemVoiceFirst)
