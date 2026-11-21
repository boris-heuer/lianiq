"""Translation worker: one daemon thread, one job at a time (contract.md §6).

Each segment is translated with ``context=()``; a cancelled job stops at its next segment
boundary. Partial output is never delivered. Logs carry the exception class name, request
id, revision, edge key, segment count and durations, never text or exception messages.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum

from lianiq.languages.errors import CapabilityMissingError
from lianiq.pipeline_types import Translator
from lianiq.text_translation.segments import join_output, split_source
from lianiq.text_translation.state import TextResult, TranslationRequest

LOGGER = logging.getLogger(__name__)
SHUTDOWN_WAIT_SECONDS = 1.0


class FailureReason(StrEnum):
    MODEL = "model"
    MEMORY = "memory"
    DEVICE = "device"  # playback only: the speakers could not be opened
    OTHER = "other"


def failure_reason(error: BaseException) -> FailureReason:
    names = {cls.__name__ for cls in type(error).__mro__}
    if isinstance(error, MemoryError) or "OutOfMemoryError" in names:
        return FailureReason.MEMORY
    if isinstance(error, RuntimeError) and "out of memory" in str(error).lower():
        return FailureReason.MEMORY  # torch CPU allocation failure
    if (
        isinstance(error, CapabilityMissingError | OSError | ImportError)
        or "ModelLoadError" in names
    ):
        return FailureReason.MODEL  # OSError covers FileNotFoundError and load I/O errors
    return FailureReason.OTHER


class _Cancelled(Exception):
    pass


@dataclass(slots=True)
class _Job:
    request: TranslationRequest
    done: Callable[[TextResult], None]
    failed: Callable[[int, FailureReason], None]
    cancelled: Callable[[int], None]
    stop: threading.Event = field(default_factory=threading.Event)


class TranslationJobs:
    def __init__(
        self,
        translator: Callable[[], Translator],
        post: Callable[[Callable[[], None]], None],
    ) -> None:
        self._translator = translator  # fetched per job: picks up an adapter rebuild
        self._post = post  # runs a callback on the GUI thread
        self._lock = threading.Condition()
        self._pending: _Job | None = None
        self._running: _Job | None = None
        self._closed = False
        self._thread: threading.Thread | None = None

    def start(
        self,
        request: TranslationRequest,
        done: Callable[[TextResult], None],
        failed: Callable[[int, FailureReason], None],
        cancelled: Callable[[int], None],
    ) -> None:
        """Queue ``request``; a running or queued job is cancelled first."""
        job = _Job(request, done, failed, cancelled)
        with self._lock:
            if self._closed:
                raise RuntimeError("Text translation jobs are shut down")
            self._cancel_locked()
            self._pending = job
            if self._thread is None:
                self._thread = threading.Thread(
                    target=self._run, name="text-translation", daemon=True
                )
                self._thread.start()
            self._lock.notify_all()

    def cancel(self) -> None:
        """The running job stops at its next segment; a queued job never starts."""
        with self._lock:
            self._cancel_locked()

    def shutdown(self) -> None:
        """Window close: cancel, stop the worker and wait at most one second."""
        with self._lock:
            self._closed = True
            self._cancel_locked()
            self._lock.notify_all()
            thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(SHUTDOWN_WAIT_SECONDS)

    @property
    def busy(self) -> bool:
        with self._lock:
            return self._running is not None or self._pending is not None

    def _cancel_locked(self) -> None:
        if self._running is not None:
            self._running.stop.set()
        if self._pending is not None:
            job, self._pending = self._pending, None
            self._post(lambda: job.cancelled(job.request.request_id))

    def _run(self) -> None:
        while True:
            with self._lock:
                while self._pending is None and not self._closed:
                    self._lock.wait()
                if self._pending is None:
                    return
                job, self._pending = self._pending, None
                self._running = job
            try:
                self._execute(job)
            finally:
                with self._lock:
                    self._running = None

    def _execute(self, job: _Job) -> None:
        request = job.request
        started = time.perf_counter()
        segments = 0
        try:
            translator = self._translator()
            count = getattr(translator, "token_count", None)
            measure = len if count is None else (lambda text: count(text, request.edge))
            lines = request.text.split("\n")
            split = split_source(request.text, measure)
            segments = sum(len(line) for line in split)
            translated: list[list[str]] = []
            for line in split:
                out: list[str] = []
                for segment in line:
                    if job.stop.is_set():
                        raise _Cancelled
                    out.append(translator.translate(segment.text, request.edge, context=()))
                translated.append(out)
            if job.stop.is_set():
                raise _Cancelled
            result = TextResult(
                request.request_id,
                request.revision,
                request.edge,
                join_output(lines, translated),
                tuple(sentence for line in translated for sentence in line),
            )
        except _Cancelled:
            self._log("cancelled", request, segments, started)
            self._post(lambda: job.cancelled(request.request_id))
        except Exception as error:  # noqa: BLE001 - mapped to a reason; message never logged
            reason = failure_reason(error)
            self._log(
                f"failed ({type(error).__name__}, {reason.value})", request, segments, started
            )
            self._post(lambda: job.failed(request.request_id, reason))
        else:
            self._log("done", request, segments, started)
            self._post(lambda: job.done(result))

    @staticmethod
    def _log(outcome: str, request: TranslationRequest, segments: int, started: float) -> None:
        LOGGER.info(
            "Text translation %s: request=%d revision=%d edge=%s segments=%d duration=%.3fs",
            outcome,
            request.request_id,
            request.revision,
            request.edge.key,
            segments,
            time.perf_counter() - started,
        )
