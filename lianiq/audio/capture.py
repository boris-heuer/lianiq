from __future__ import annotations

import logging
import threading
from collections.abc import Callable

import numpy as np

from lianiq.audio.resampler import convert_capture_audio
from lianiq.audio.segmenter import UtteranceSegmenter
from lianiq.config import AudioConfig
from lianiq.domain import AudioUtterance

LOGGER = logging.getLogger(__name__)


class MicrophoneCapture:
    def __init__(
        self,
        config: AudioConfig,
        on_utterance: Callable[[AudioUtterance], None],
        on_level: Callable[[float], None] | None = None,
        on_error: Callable[[str], None] | None = None,
    ) -> None:
        self.config = config
        self.on_utterance = on_utterance
        self.on_level = on_level
        self.on_error = on_error
        self._stream = None
        # The resolved endpoint's runtime index (CAP-0168 contract §4 "Opening"); ``None``
        # opens PortAudio's default device without WASAPI settings.
        self.device: int | None = None
        self._native_rate: int | None = None  # set when the T3 fallback resamples
        self._muted = threading.Event()
        self._segmenter_lock = threading.Lock()
        self._segmenter = self._new_segmenter()

    def _new_segmenter(self) -> UtteranceSegmenter:
        return UtteranceSegmenter(
            sample_rate=self.config.sample_rate,
            chunk_ms=self.config.chunk_ms,
            start_rms=self.config.start_rms,
            end_silence_ms=self.config.end_silence_ms,
            pre_roll_ms=self.config.pre_roll_ms,
            min_speech_ms=self.config.min_speech_ms,
            max_speech_seconds=self.config.max_speech_seconds,
        )

    @property
    def running(self) -> bool:
        return self._stream is not None

    def set_muted(self, muted: bool) -> None:
        if muted:
            self._muted.set()
            with self._segmenter_lock:
                self._segmenter.reset()
        else:
            self._muted.clear()

    def start(self) -> None:
        if self.running:
            return
        try:
            import sounddevice as sd
        except ImportError as exc:
            raise RuntimeError("sounddevice is not installed") from exc
        self._native_rate = None
        if self.device is None:
            self._stream = self._open(sd, self.config.sample_rate)
        else:
            try:
                # WASAPI shared mode converts the endpoint rate to 16 kHz (AC-21).
                self._stream = self._open(
                    sd, self.config.sample_rate, sd.WasapiSettings(auto_convert=True)
                )
            except sd.PortAudioError:
                # Spec §9 T3: a device that rejects auto-convert is opened at its own rate
                # and resampled by ``resampler.py``; there is no fallback to another device.
                rate = round(float(sd.query_devices(self.device)["default_samplerate"]))
                self._stream = self._open(sd, rate)
                self._native_rate = rate
        try:
            self._stream.start()
        except BaseException:
            # An opened stream that fails to start is closed, so the device is not held.
            stream, self._stream, self._native_rate = self._stream, None, None
            stream.close()
            raise
        LOGGER.info("Microphone capture started (%s Hz)", self._native_rate or "16000")

    def _open(self, sd, rate: int, extra_settings=None):
        return sd.InputStream(
            samplerate=rate,
            blocksize=round(rate * self.config.chunk_ms / 1000),
            channels=1,
            dtype="float32",
            device=self.device,
            callback=self._callback,
            extra_settings=extra_settings,
        )

    @property
    def stream_failed(self) -> bool:
        """A running stream that PortAudio stopped on its own (device fault or removal)."""
        return self._stream is not None and not getattr(self._stream, "active", True)

    def stop(self) -> None:
        stream, self._stream = self._stream, None
        if stream is not None:
            stream.stop()
            stream.close()
        with self._segmenter_lock:
            self._segmenter.reset()
        LOGGER.info("Microphone capture stopped")

    def _callback(self, indata: np.ndarray, _frames: int, _time: object, status: object) -> None:
        if status:
            LOGGER.warning("Audio status: %s", status)
        if self._muted.is_set():
            return
        try:
            frame = indata[:, 0].copy()
            if self._native_rate is not None:
                frame = convert_capture_audio(frame, self._native_rate, self.config.sample_rate)
            if self.on_level:
                level = float(np.sqrt(np.mean(np.square(frame), dtype=np.float64)))
                self.on_level(min(level / max(self.config.start_rms * 3, 0.001), 1.0))
            with self._segmenter_lock:
                samples = self._segmenter.push(frame)
            if samples is not None:
                self.on_utterance(AudioUtterance(samples, self.config.sample_rate))
        except Exception as exc:  # PortAudio callbacks must never leak exceptions.
            LOGGER.exception("Audio callback failed")
            if self.on_error:
                self.on_error(str(exc))
