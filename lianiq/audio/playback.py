from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

from lianiq.audio.resampler import convert_capture_audio


def play_wav(path: Path, output_device: int | None = None, *, auto_convert: bool = False) -> None:
    """Play a 16-bit WAV, blocking; ``auto_convert`` opens a WASAPI index (CAP-0168 §4).

    With ``auto_convert`` WASAPI shared mode converts the WAV rate; a device that rejects
    it gets the audio resampled to its own rate by ``resampler.py`` (spec §9 T3).
    """
    try:
        import sounddevice as sd
    except ImportError as exc:
        raise RuntimeError("sounddevice is not installed") from exc
    with wave.open(str(path), "rb") as wav:
        channels = wav.getnchannels()
        sample_width = wav.getsampwidth()
        sample_rate = wav.getframerate()
        frames = wav.readframes(wav.getnframes())
    if sample_width != 2:
        raise RuntimeError(f"Unsupported WAV sample width: {sample_width * 8} bit")
    audio = np.frombuffer(frames, dtype=np.int16)
    if channels > 1:
        audio = audio.reshape(-1, channels)
    if not auto_convert or output_device is None:
        sd.play(audio, sample_rate, device=output_device, blocking=True)
        return
    try:
        sd.play(
            audio,
            sample_rate,
            device=output_device,
            blocking=True,
            extra_settings=sd.WasapiSettings(auto_convert=True),
        )
    except sd.PortAudioError:
        rate = round(float(sd.query_devices(output_device)["default_samplerate"]))
        converted = convert_capture_audio(audio.astype(np.float32) / 32768.0, sample_rate, rate)
        sd.play(converted, rate, device=output_device, blocking=True)
