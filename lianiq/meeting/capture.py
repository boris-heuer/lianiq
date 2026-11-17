"""One meeting input: an ``EndpointCaptureStream`` whose segmenter obeys the feedback guard.

Qt-free (CAP-0177 contract.md §4 and §5). Each input owns its ``UtteranceSegmenter``; a
speech pause (``audio.end_silence_ms``) ends a contribution without any button press. While
the guard mutes the input, every block is discarded and the segmenter is reset, so muted
audio never becomes a contribution and is not buffered. ``flush`` closes a running
contribution when a playback can no longer wait for it (``CLOSE_AND_PLAY``).

``process_block`` runs on the capture's processing thread, never in the audio callback;
``speaking``, ``flush`` and ``mark_muted`` are called from the inference worker, so the
segmenter is guarded by a lock.
"""

from __future__ import annotations

import threading
from collections.abc import Callable

import numpy as np

from lianiq.audio.capture_stream import EndpointCaptureStream, StreamFactory
from lianiq.call_bridge.contracts import AudioEndpointRef
from lianiq.config import AudioConfig
from lianiq.domain import AudioUtterance


class MeetingCapture(EndpointCaptureStream):
    def __init__(
        self,
        endpoint: AudioEndpointRef,
        config: AudioConfig,
        on_utterance: Callable[[AudioUtterance], None],
        *,
        is_muted: Callable[[], bool],
        on_unmuted: Callable[[], None],
        on_level: Callable[[float], None] | None = None,
        stream_factory: StreamFactory | None = None,
    ) -> None:
        self._segment_lock = threading.RLock()
        self._is_muted = is_muted
        self._on_unmuted = on_unmuted
        self._muted = False
        super().__init__(
            endpoint, config, on_utterance, on_level=on_level, stream_factory=stream_factory
        )

    @property
    def speaking(self) -> bool:
        """Whether a contribution is running (the segmenter is not idle)."""
        with self._segment_lock:
            return self._segmenter.speaking

    def mark_muted(self) -> None:
        """A playback muted this input: drop its running segment now."""
        with self._segment_lock:
            self._muted = True
            self._segmenter.reset()

    def flush(self) -> None:
        """Close the running contribution at this point; it is processed, not dropped."""
        with self._segment_lock:
            samples = self._segmenter.flush()
        if samples is not None:
            self.on_utterance(AudioUtterance(samples, self.config.sample_rate))

    def process_block(self, frame: np.ndarray) -> None:
        """Segment one ``chunk_ms`` block at the target rate, or discard it while muted."""
        unmuted = False
        with self._segment_lock:
            if self._is_muted():
                self._muted = True
                self._segmenter.reset()
                return
            if self._muted:
                self._muted = False
                unmuted = True
            samples = self._segmenter.push(frame)
        if unmuted:
            self._on_unmuted()
        if samples is not None:
            self.on_utterance(AudioUtterance(samples, self.config.sample_rate))

    def _consume_target_blocks(self) -> None:
        while self._pending.size >= self._target_block_samples:
            frame = self._pending[: self._target_block_samples]
            self._pending = self._pending[self._target_block_samples :]
            if self.on_level:
                level = float(np.sqrt(np.mean(np.square(frame), dtype=np.float64)))
                self.on_level(min(level / max(self.config.start_rms * 3, 0.001), 1.0))
            self.process_block(frame)
