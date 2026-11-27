"""Windows system voice in front of a bundled voice (lianiq#81).

Qt-free. ``SystemVoiceFirst`` speaks one language with an installed Windows speech voice
(OneCore, ``Windows.Media.SpeechSynthesis``) whose language tag matches, for example
``zh-CN``; without such a voice, or without the ``winrt`` packages, every call goes to the
bundled engine (the sherpa-onnx aishell3 voice for Mandarin). Lianiq ships no file of the
system voice: Windows provides it once the user has installed the speech pack.
"""

from __future__ import annotations

import asyncio
import io
import tempfile
import threading
import wave
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path

import numpy as np

from lianiq.tts.voice_controls import VoiceControls, VoiceOptions

SYSTEM_DEVICE = "windows"


def installed_voices(tag: str) -> list[object]:
    """The installed Windows voices whose language starts with ``tag``; empty if unavailable."""
    try:
        from winrt.windows.media.speechsynthesis import SpeechSynthesizer

        voices = list(SpeechSynthesizer.all_voices)
    except Exception:  # noqa: BLE001 - broken PyWinRT or speech service: bundled voice
        return []
    prefix = tag.lower()
    return [voice for voice in voices if str(voice.language).lower().startswith(prefix)]


async def _wav_bytes(voice: object, text: str, options: VoiceOptions) -> bytes:
    from winrt.windows.media.speechsynthesis import SpeechSynthesizer
    from winrt.windows.storage.streams import DataReader

    synthesizer = SpeechSynthesizer()
    synthesizer.voice = voice
    synthesizer.options.speaking_rate = options.rate
    synthesizer.options.audio_volume = options.volume
    stream = await synthesizer.synthesize_text_to_stream_async(text)
    size = int(stream.size)
    reader = DataReader(stream.get_input_stream_at(0))
    await reader.load_async(size)
    data = bytearray(size)
    reader.read_bytes(data)
    return bytes(data)


def _pcm(wav: bytes) -> tuple[np.ndarray, int]:
    with wave.open(io.BytesIO(wav)) as reader:
        if reader.getsampwidth() != 2:
            raise RuntimeError("The Windows voice returned audio that is not 16-bit PCM")
        frames = np.frombuffer(reader.readframes(reader.getnframes()), dtype="<i2")
        channels = reader.getnchannels()
        if channels > 1:
            frames = frames.reshape(-1, channels)[:, 0]
        if frames.size == 0:
            raise RuntimeError("The Windows voice produced no audio for the given text")
        return frames.copy(), int(reader.getframerate())


class SystemVoiceFirst:
    """One language's engine: a matching Windows voice if installed, else ``fallback``.

    The voice list is read on first use (worker thread), never in ``controls``.
    """

    def __init__(
        self,
        fallback: object,
        tag: str,
        find: Callable[[str], Sequence[object]] = installed_voices,
        render: Callable[[object, str, VoiceOptions], bytes] | None = None,
    ) -> None:
        self.fallback = fallback
        self.tag = tag
        self._find = find
        self._render = render or (lambda v, t, o: asyncio.run(_wav_bytes(v, t, o)))
        self._voices: list[object] | None = None
        self._lock = threading.Lock()

    def system_voices(self) -> list[object]:
        with self._lock:
            if self._voices is None:
                self._voices = list(self._find(self.tag))
            return self._voices

    @property
    def device(self) -> str:
        if self._voices:
            return SYSTEM_DEVICE
        return str(getattr(self.fallback, "device", "unknown"))

    def validate_voice_files(self, languages: Iterable[str] | None = None) -> None:
        validate = getattr(self.fallback, "validate_voice_files", None)
        if validate is not None and not self.system_voices():
            validate(languages)

    def controls(self, language: str) -> VoiceControls:
        if self._voices:
            return VoiceControls(len(self._voices), rate=True, volume=True)
        return self.fallback.controls(language)

    def load_controls(self, language: str) -> VoiceControls:
        if self.system_voices():
            return self.controls(language)
        load = getattr(self.fallback, "load_controls", None)
        return self.fallback.controls(language) if load is None else load(language)

    def warm_up(self, languages: Iterable[str]) -> None:
        languages = tuple(languages)
        if not self.system_voices():
            self.fallback.warm_up(languages)
            return
        registry = getattr(self.fallback, "registry", None)
        for language in languages:
            sample = registry.get(language).native_name if registry else "1"
            self.synthesize_pcm(sample, language)

    def synthesize_pcm(
        self, text: str, language: str, options: VoiceOptions | None = None
    ) -> tuple[np.ndarray, int]:
        """PCM16 mono and rate; a speaker beyond the installed voices uses the first one."""
        voices = self.system_voices()
        if not voices:
            return self.fallback.synthesize_pcm(text, language, options)
        options = options or VoiceOptions()
        index = options.speaker if options.speaker is not None else 0
        voice = voices[index] if index < len(voices) else voices[0]
        return _pcm(self._render(voice, text, options))

    def synthesize(self, text: str, language: str, options: VoiceOptions | None = None) -> Path:
        if not self.system_voices():
            return self.fallback.synthesize(text, language, options)
        pcm, sample_rate = self.synthesize_pcm(text, language, options)
        with tempfile.NamedTemporaryFile(prefix="lianiq-", suffix=".wav", delete=False) as handle:
            output = Path(handle.name)
        try:
            with wave.open(str(output), "wb") as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(sample_rate)
                wav_file.writeframes(pcm.tobytes())
            return output
        except Exception:
            output.unlink(missing_ok=True)
            raise
