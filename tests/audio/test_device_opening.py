"""Conversation streams open the resolved endpoint by index (CAP-0168 contract §4; AC-21 Unit).

A fake ``sounddevice`` module records how ``MicrophoneCapture`` and ``play_wav`` open the
device: by runtime index with ``WasapiSettings(auto_convert=True)``, and the spec §9 T3
fallback (native rate plus ``resampler.py``) when a device rejects auto-convert. The T5
PortAudio re-initialisation wrapper is covered here too.
"""

from __future__ import annotations

import sys
import types
import wave

import numpy as np
import pytest

from lianiq.audio import device_inventory
from lianiq.audio.capture import MicrophoneCapture
from lianiq.audio.playback import play_wav
from lianiq.config import AudioConfig


class PortAudioError(Exception):
    pass


class WasapiSettings:
    def __init__(self, exclusive=False, auto_convert=False, explicit_sample_format=False):
        self.auto_convert = auto_convert


def fake_sounddevice(monkeypatch, *, reject_auto_convert: bool = False, fail_start=False):
    module = types.SimpleNamespace(
        PortAudioError=PortAudioError,
        WasapiSettings=WasapiSettings,
        opened=[],
        played=[],
        calls=[],
        closed=0,
    )

    class InputStream:
        def __init__(self, **kwargs):
            if reject_auto_convert and kwargs.get("extra_settings") is not None:
                raise PortAudioError("Invalid sample rate")
            module.opened.append(kwargs)
            self.callback = kwargs["callback"]
            self.active = True

        def start(self):
            if fail_start:
                raise PortAudioError("Device unavailable")

        def stop(self):
            return None

        def close(self):
            module.closed += 1

    def play(data, samplerate, **kwargs):
        if reject_auto_convert and kwargs.get("extra_settings") is not None:
            raise PortAudioError("Invalid sample rate")
        module.played.append((data, samplerate, kwargs))

    module.InputStream = InputStream
    module.play = play
    module.query_devices = lambda index: {"default_samplerate": 48_000.0}
    module._terminate = lambda: module.calls.append("terminate")
    module._initialize = lambda: module.calls.append("initialize")
    monkeypatch.setitem(sys.modules, "sounddevice", module)
    return module


def wav_file(path, rate=22_050):
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(np.zeros(rate // 10, dtype=np.int16).tobytes())
    return path


def test_ac21_capture_opens_the_resolved_index_with_wasapi_auto_convert(monkeypatch) -> None:
    sd = fake_sounddevice(monkeypatch)
    capture = MicrophoneCapture(AudioConfig(), on_utterance=lambda _u: None)
    capture.device = 7
    capture.start()

    opened = sd.opened[0]
    assert opened["device"] == 7 and opened["samplerate"] == 16_000
    assert opened["extra_settings"].auto_convert is True
    assert not capture.stream_failed
    capture._stream.active = False  # PortAudio stopped the stream (device removed)
    assert capture.stream_failed
    capture.stop()


def test_capture_stop_closes_the_stream(monkeypatch) -> None:
    sd = fake_sounddevice(monkeypatch)
    capture = MicrophoneCapture(AudioConfig(), on_utterance=lambda _u: None)
    capture.device = 7
    capture.start()
    capture.stop()
    assert sd.closed == 1 and not capture.running


def test_capture_that_fails_to_start_closes_the_stream(monkeypatch) -> None:
    sd = fake_sounddevice(monkeypatch, fail_start=True)
    capture = MicrophoneCapture(AudioConfig(), on_utterance=lambda _u: None)
    capture.device = 7
    with pytest.raises(PortAudioError, match="Device unavailable"):
        capture.start()
    assert sd.closed == 1 and not capture.running


def test_ac21_capture_without_a_resolved_index_uses_no_wasapi_settings(monkeypatch) -> None:
    sd = fake_sounddevice(monkeypatch)
    MicrophoneCapture(AudioConfig(), on_utterance=lambda _u: None).start()
    assert sd.opened[0]["device"] is None and sd.opened[0]["extra_settings"] is None


def test_t3_capture_falls_back_to_the_native_rate_and_resamples(monkeypatch) -> None:
    sd = fake_sounddevice(monkeypatch, reject_auto_convert=True)
    levels = []
    capture = MicrophoneCapture(
        AudioConfig(chunk_ms=30), on_utterance=lambda _u: None, on_level=levels.append
    )
    capture.device = 7
    capture.start()

    opened = sd.opened[0]
    assert opened["device"] == 7 and opened["samplerate"] == 48_000
    assert opened["blocksize"] == 1_440 and opened["extra_settings"] is None
    pushed = []
    capture._segmenter = types.SimpleNamespace(push=pushed.append, reset=lambda: None)
    opened["callback"](np.zeros((1_440, 1), dtype=np.float32), 1_440, None, None)
    assert pushed[0].shape == (480,)  # 30 ms at 16 kHz for the segmenter


def test_ac21_play_wav_opens_the_index_with_auto_convert(monkeypatch, tmp_path) -> None:
    sd = fake_sounddevice(monkeypatch)
    play_wav(wav_file(tmp_path / "t.wav"), 5, auto_convert=True)
    _data, rate, kwargs = sd.played[0]
    assert rate == 22_050 and kwargs["device"] == 5 and kwargs["blocking"] is True
    assert kwargs["extra_settings"].auto_convert is True


def test_play_wav_without_auto_convert_is_unchanged(monkeypatch, tmp_path) -> None:
    sd = fake_sounddevice(monkeypatch)
    play_wav(wav_file(tmp_path / "t.wav"), 5)
    assert "extra_settings" not in sd.played[0][2]  # the Call Bridge path


def test_t3_play_wav_resamples_to_the_device_rate(monkeypatch, tmp_path) -> None:
    sd = fake_sounddevice(monkeypatch, reject_auto_convert=True)
    play_wav(wav_file(tmp_path / "t.wav"), 5, auto_convert=True)
    data, rate, kwargs = sd.played[0]
    assert rate == 48_000 and data.dtype == np.float32 and "extra_settings" not in kwargs
    assert data.shape == (round(2_205 * 48_000 / 22_050),)


def test_t5_reinitialize_portaudio_terminates_then_initializes(monkeypatch) -> None:
    sd = fake_sounddevice(monkeypatch)
    device_inventory.reinitialize_portaudio()
    assert sd.calls == ["terminate", "initialize"]


def test_read_inventory_reads_all_host_apis_and_native_identities(monkeypatch) -> None:
    sd = fake_sounddevice(monkeypatch)
    sd.query_hostapis = lambda: [{"name": "MME"}, {"name": "Windows WASAPI"}]
    sd.query_devices = lambda: [
        {
            "name": "Mic",
            "hostapi": 0,
            "max_input_channels": 1,
            "max_output_channels": 0,
            "default_samplerate": 44_100.0,
        },
        {
            "name": "Mic",
            "hostapi": 1,
            "max_input_channels": 1,
            "max_output_channels": 0,
            "default_samplerate": 48_000.0,
        },
    ]
    from lianiq.audio.windows_endpoints import NativeEndpointIdentity
    from tests._fake_devices import CAPTURE, native_id

    natives = [NativeEndpointIdentity(native_id(CAPTURE, "m"), CAPTURE, ("Mic",))]
    monkeypatch.setattr(device_inventory, "list_windows_endpoint_identities", lambda: natives)
    inventory = device_inventory.read_inventory()
    assert [(e.display_name, e.runtime_index) for e in inventory.endpoints] == [("Mic", 1)]
    assert inventory.legacy_names == {0: "Mic", 1: "Mic"}
    assert device_inventory.read_native_ids() == {native_id(CAPTURE, "m"): "Mic"}


def test_missing_sounddevice_is_a_runtime_error(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "sounddevice", None)
    with pytest.raises(RuntimeError, match="sounddevice is not installed"):
        device_inventory.reinitialize_portaudio()
