from __future__ import annotations

import logging
import threading
from collections.abc import Callable

import numpy as np

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
        blocksize = round(self.config.sample_rate * self.config.chunk_ms / 1000)
        self._stream = sd.InputStream(
            samplerate=self.config.sample_rate,
            blocksize=blocksize,
            channels=1,
            dtype="float32",
            device=self.config.input_device,
            callback=self._callback,
        )
        self._stream.start()
        LOGGER.info("Microphone capture started")

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
