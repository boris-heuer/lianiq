from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Protocol

import numpy as np

from lianiq.audio.resampler import convert_capture_audio
from lianiq.audio.ring_buffer import AudioRingBuffer
from lianiq.audio.segmenter import UtteranceSegmenter
from lianiq.call_bridge.contracts import AudioEndpointRef, EndpointFlow
from lianiq.config import AudioConfig
from lianiq.domain import AudioUtterance

LOGGER = logging.getLogger(__name__)


class StreamFactory(Protocol):
    def __call__(self, **kwargs): ...


class EndpointCaptureStream:
    """Explicit endpoint capture with a callback-only bounded audio handoff."""

    def __init__(
        self,
        endpoint: AudioEndpointRef,
        config: AudioConfig,
        on_utterance: Callable[[AudioUtterance], None],
        on_level: Callable[[float], None] | None = None,
        on_error: Callable[[str], None] | None = None,
        stream_factory: StreamFactory | None = None,
    ) -> None:
        if endpoint.flow is not EndpointFlow.CAPTURE:
            raise ValueError("EndpointCaptureStream requires a capture endpoint")
        self.endpoint = endpoint
        self.config = config
        self.on_utterance = on_utterance
        self.on_level = on_level
        self.on_error = on_error
        self._stream_factory = stream_factory
        self._stream = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._data_ready = threading.Event()
        self._target_block_samples = round(config.sample_rate * config.chunk_ms / 1_000)
        self._pending = np.empty(0, dtype=np.float32)
        self._segmenter = self._new_segmenter()
        self._configure_endpoint(endpoint)

    @property
    def running(self) -> bool:
        return self._stream is not None

    def rebind(self, endpoint: AudioEndpointRef) -> None:
        if self.running:
            raise RuntimeError("Stop capture before rebinding an endpoint")
        if endpoint.endpoint_id != self.endpoint.endpoint_id:
            raise ValueError("Recovered endpoint identity does not match configured endpoint")
        self._configure_endpoint(endpoint)

    def _configure_endpoint(self, endpoint: AudioEndpointRef) -> None:
        self.endpoint = endpoint
        self._channels = min(endpoint.channels, 2)
        self._source_block_frames = round(endpoint.sample_rate * self.config.chunk_ms / 1_000)
        capacity_scalars = endpoint.sample_rate * self._channels * 2
        self._buffer = AudioRingBuffer(capacity_scalars, endpoint.sample_rate * self._channels)

    def start(self) -> None:
        if self.running:
            return
        factory = self._stream_factory
        if factory is None:
            try:
                import sounddevice as sd
            except ImportError as exc:
                raise RuntimeError("sounddevice is not installed") from exc
            factory = sd.InputStream
        self._stop.clear()
        self._data_ready.clear()
        self._pending = np.empty(0, dtype=np.float32)
        self._segmenter = self._new_segmenter()
        self._thread = threading.Thread(
            target=self._process_audio,
            name=f"audio-capture-{self.endpoint.runtime_index}",
            daemon=True,
        )
        self._thread.start()
        try:
            self._stream = factory(
                samplerate=self.endpoint.sample_rate,
                blocksize=self._source_block_frames,
                channels=self._channels,
                dtype="float32",
                device=self.endpoint.runtime_index,
                callback=self._callback,
            )
            self._stream.start()
        except Exception:
            self._stream = None
            self._stop.set()
            self._data_ready.set()
            self._thread.join(timeout=1.0)
            self._thread = None
            raise

    def stop(self) -> None:
        stream, self._stream = self._stream, None
        if stream is not None:
            stream.stop()
            stream.close()
        self._stop.set()
        self._data_ready.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        self._segmenter.reset()

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

    def _callback(
        self, indata: np.ndarray, _frames: int, _time_info: object, status: object
    ) -> None:
        if status:
            LOGGER.warning(
                "Call bridge capture status: endpoint_role=capture category=audio_status"
            )
            if self.on_error:
                self.on_error("capture_stream_status")
        try:
            self._buffer.write(indata.reshape(-1), time.monotonic())
            self._data_ready.set()
        except Exception:
            LOGGER.exception("Call bridge audio callback failed")
            if self.on_error:
                self.on_error("capture_callback_failed")

    def _process_audio(self) -> None:
        read_size = self._source_block_frames * self._channels
        while not self._stop.is_set():
            self._data_ready.wait(timeout=0.2)
            self._data_ready.clear()
            while True:
                chunk = self._buffer.read(read_size)
                if chunk is None:
                    break
                samples = chunk.samples
                complete = samples.size - (samples.size % self._channels)
                if complete == 0:
                    continue
                frames = samples[:complete].reshape(-1, self._channels)
                converted = convert_capture_audio(
                    frames,
                    self.endpoint.sample_rate,
                    self.config.sample_rate,
                )
                if converted.size:
                    self._pending = np.concatenate((self._pending, converted))
                self._consume_target_blocks()

    def _consume_target_blocks(self) -> None:
        while self._pending.size >= self._target_block_samples:
            frame = self._pending[: self._target_block_samples]
            self._pending = self._pending[self._target_block_samples :]
            if self.on_level:
                level = float(np.sqrt(np.mean(np.square(frame), dtype=np.float64)))
                self.on_level(min(level / max(self.config.start_rms * 3, 0.001), 1.0))
            utterance = self._segmenter.push(frame)
            if utterance is not None:
                self.on_utterance(AudioUtterance(utterance, self.config.sample_rate))
