from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol

from lianiq.call_bridge.contracts import (
    BridgeEvent,
    BridgeEventKind,
    LaneId,
)
from lianiq.call_bridge.health import LaneHealthSnapshot
from lianiq.call_bridge.inference_scheduler import InferenceScheduler
from lianiq.domain import AudioUtterance, Language, TranslationResult
from lianiq.pipeline import SpeechRecognizer, Synthesizer, Translator

LOGGER = logging.getLogger(__name__)


class Playback(Protocol):
    def __call__(self, output: Path | str) -> None: ...


class _StageFailure(RuntimeError):
    def __init__(self, category: str) -> None:
        super().__init__(category)
        self.category = category


@dataclass(frozen=True, slots=True)
class _PendingUtterance:
    sequence: int
    enqueued_at: float
    utterance: AudioUtterance


class TranslationLane:
    """One fixed-direction, ordered, fail-closed translation lane."""

    def __init__(
        self,
        lane_id: LaneId,
        source_language: Language,
        target_language: Language,
        recognizer: SpeechRecognizer,
        translator: Translator,
        synthesizer: Synthesizer,
        playback: Playback,
        scheduler: InferenceScheduler,
        *,
        max_pending_age_ms: int = 4_000,
        queue_size: int = 2,
        on_result: Callable[[TranslationResult], None] | None = None,
        on_event: Callable[[BridgeEvent], None] | None = None,
    ) -> None:
        if source_language is target_language:
            raise ValueError("Translation lane source and target must differ")
        if max_pending_age_ms <= 0 or queue_size <= 0:
            raise ValueError("queue_size and max_pending_age_ms must be positive")
        self.lane_id = lane_id
        self.source_language = source_language
        self.target_language = target_language
        self.recognizer = recognizer
        self.translator = translator
        self.synthesizer = synthesizer
        self.playback = playback
        self.scheduler = scheduler
        self.max_pending_age_seconds = max_pending_age_ms / 1_000
        self.queue_size = queue_size
        self.on_result = on_result
        self.on_event = on_event
        self._queue: queue.Queue[_PendingUtterance | None] = queue.Queue(maxsize=queue_size)
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._available = threading.Event()
        self._available.set()
        self._sequence = 0
        self._sequence_lock = threading.Lock()
        self._health_lock = threading.Lock()
        self._health = LaneHealthSnapshot()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def health(self) -> LaneHealthSnapshot:
        with self._health_lock:
            return self._health

    def start(self) -> None:
        if self.running:
            return
        self._queue = queue.Queue(maxsize=self.queue_size)
        self._stop.clear()
        self._available.set()
        self._thread = threading.Thread(
            target=self._run,
            name=f"call-bridge-{self.lane_id.value}",
            daemon=True,
        )
        self._thread.start()

    def submit(self, utterance: AudioUtterance) -> bool:
        if self._stop.is_set() or not self._available.is_set():
            self._emit(BridgeEventKind.DROPPED, "lane_unavailable", "utterance_dropped")
            return False
        with self._sequence_lock:
            self._sequence += 1
            pending = _PendingUtterance(self._sequence, time.monotonic(), utterance)
        try:
            self._queue.put_nowait(pending)
            return True
        except queue.Full:
            self._drop_oldest("queue_pressure")
            try:
                self._queue.put_nowait(pending)
                return True
            except queue.Full:
                self._emit(
                    BridgeEventKind.DROPPED,
                    "queue_pressure",
                    "utterance_dropped",
                    pending.sequence,
                )
                return False

    def set_available(self, available: bool) -> None:
        if available:
            self._available.set()
            return
        self._available.clear()
        self._drain_pending("endpoint_unavailable")

    def wait_until_idle(self, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while self._queue.unfinished_tasks:
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.005)
        return True

    def stop(self, timeout: float = 10.0) -> bool:
        self._stop.set()
        self._available.clear()
        self._drain_pending("shutdown")
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            self._drop_oldest("shutdown")
            self._queue.put_nowait(None)
        thread = self._thread
        if thread is None:
            return True
        thread.join(timeout=timeout)
        stopped = not thread.is_alive()
        if stopped:
            self._thread = None
        return stopped

    def _run(self) -> None:
        while True:
            try:
                item = self._queue.get(timeout=0.2)
            except queue.Empty:
                if self._stop.is_set():
                    return
                continue
            try:
                if item is None:
                    return
                age = time.monotonic() - item.enqueued_at
                if age > self.max_pending_age_seconds:
                    self._emit(
                        BridgeEventKind.DROPPED,
                        "stale_queue_item",
                        "utterance_dropped",
                        item.sequence,
                    )
                    continue
                if not self._available.is_set():
                    self._emit(
                        BridgeEventKind.DROPPED,
                        "lane_unavailable",
                        "utterance_dropped",
                        item.sequence,
                    )
                    continue
                with self._health_lock:
                    self._health = replace(
                        self._health,
                        queue_age_ms=age * 1_000,
                        captured_seconds=item.utterance.samples.size / item.utterance.sample_rate,
                    )
                self.scheduler.run(lambda pending=item: self._process(pending))
            except Exception as exc:  # noqa: BLE001 - worker failure boundary.
                category = exc.category if isinstance(exc, _StageFailure) else "internal_failure"
                LOGGER.error(
                    "Call bridge lane failed: lane=%s category=%s",
                    self.lane_id.value,
                    category,
                )
                self._emit(
                    BridgeEventKind.ERROR,
                    category,
                    "inference_failed",
                    item.sequence if item is not None else None,
                )
            finally:
                self._queue.task_done()

    def _process(self, item: _PendingUtterance) -> None:
        utterance = item.utterance
        started = time.perf_counter()
        try:
            transcript = self.recognizer.transcribe(
                utterance.samples,
                utterance.sample_rate,
                self.source_language,
            )
        except Exception:  # noqa: BLE001 - external STT adapter boundary.
            raise _StageFailure("stt_failure") from None
        stt_seconds = time.perf_counter() - started
        if not transcript.text.strip():
            return
        translated_started = time.perf_counter()
        try:
            translated = self.translator.translate(
                transcript.text,
                self.source_language,
                self.target_language,
            )
        except Exception:  # noqa: BLE001 - external translation adapter boundary.
            raise _StageFailure("translation_failure") from None
        translation_seconds = time.perf_counter() - translated_started
        tts_started = time.perf_counter()
        try:
            output = self.synthesizer.synthesize(translated, self.target_language)
        except Exception:  # noqa: BLE001 - external TTS adapter boundary.
            raise _StageFailure("tts_failure") from None
        tts_seconds = time.perf_counter() - tts_started
        playback_started = time.perf_counter()
        try:
            if not self._available.is_set():
                self._emit(
                    BridgeEventKind.DROPPED,
                    "lane_unavailable",
                    "synthesized_output_muted",
                    item.sequence,
                )
                return
            try:
                self.playback(output)
            except Exception:  # noqa: BLE001 - external playback adapter boundary.
                raise _StageFailure("playback_failure") from None
        finally:
            if isinstance(output, Path):
                output.unlink(missing_ok=True)
        playback_seconds = time.perf_counter() - playback_started
        result = TranslationResult(
            source_text=transcript.text,
            translated_text=translated,
            source_language=self.source_language,
            target_language=self.target_language,
            stt_seconds=stt_seconds,
            translation_seconds=translation_seconds,
            tts_seconds=tts_seconds,
        )
        if self.on_result:
            self.on_result(result)
        with self._health_lock:
            self._health = LaneHealthSnapshot(
                captured_seconds=utterance.samples.size / utterance.sample_rate,
                queue_age_ms=self._health.queue_age_ms,
                dropped_turns=self._health.dropped_turns,
                stt_ms=stt_seconds * 1_000,
                translation_ms=translation_seconds * 1_000,
                tts_ms=tts_seconds * 1_000,
                playback_ms=playback_seconds * 1_000,
            )
        LOGGER.info(
            "Call bridge lane metrics: lane=%s captured_ms=%.1f queue_ms=%.1f "
            "stt_ms=%.1f translation_ms=%.1f tts_ms=%.1f playback_ms=%.1f dropped=%d",
            self.lane_id.value,
            self._health.captured_seconds * 1_000,
            self._health.queue_age_ms,
            self._health.stt_ms,
            self._health.translation_ms,
            self._health.tts_ms,
            self._health.playback_ms,
            self._health.dropped_turns,
        )

    def _drop_oldest(self, category: str) -> None:
        try:
            dropped = self._queue.get_nowait()
        except queue.Empty:
            return
        self._queue.task_done()
        if dropped is not None:
            self._emit(
                BridgeEventKind.DROPPED,
                category,
                "utterance_dropped",
                dropped.sequence,
            )

    def _drain_pending(self, category: str) -> None:
        while True:
            try:
                pending = self._queue.get_nowait()
            except queue.Empty:
                return
            self._queue.task_done()
            if pending is not None:
                self._emit(
                    BridgeEventKind.DROPPED,
                    category,
                    "utterance_dropped",
                    pending.sequence,
                )

    def _emit(
        self,
        kind: BridgeEventKind,
        category: str,
        message: str,
        sequence: int | None = None,
    ) -> None:
        if self.on_event:
            self.on_event(BridgeEvent(self.lane_id, kind, category, message, sequence))
        if kind is BridgeEventKind.DROPPED:
            with self._health_lock:
                current = self._health
                self._health = LaneHealthSnapshot(
                    captured_seconds=current.captured_seconds,
                    queue_age_ms=current.queue_age_ms,
                    dropped_turns=current.dropped_turns + 1,
                    stt_ms=current.stt_ms,
                    translation_ms=current.translation_ms,
                    tts_ms=current.tts_ms,
                    playback_ms=current.playback_ms,
                )
