"""The translation pipeline and its single-consumer worker (``PipelineRunner``).

CAP-0168 file-size split: ``TranslationPipeline`` lives in ``pipeline_translation.py`` (with
its ``pipeline_adapters.py`` and ``pipeline_held.py`` bases) and the adapter protocols, bound
turns and notice events in ``pipeline_types.py``. They are re-exported here, so every
established ``lianiq.pipeline`` import path keeps working.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Callable
from uuid import UUID

from lianiq.conversation.routing import HeldTurn
from lianiq.domain import AudioUtterance, TranslationResult
from lianiq.languages.modes import SessionPair
from lianiq.languages.registry import LanguageId
from lianiq.pipeline_translation import TranslationPipeline
from lianiq.pipeline_types import (
    DEFAULT_DETECTION_MIN_PROBABILITY,  # noqa: F401 - re-export
    AdapterFactories,  # noqa: F401 - re-export
    BoundUtterance,
    FailureReason,  # noqa: F401 - re-export
    PipelineEvent,
    PipelineEventKind,
    SpeechRecognizer,  # noqa: F401 - re-export
    Synthesizer,  # noqa: F401 - re-export
    Translator,  # noqa: F401 - re-export
    _captured_at,  # noqa: F401 - re-export
    _RetainedTurn,  # noqa: F401 - re-export
    _warm_up,  # noqa: F401 - re-export
    bind_utterance,
    classify_failure,
)

LOGGER = logging.getLogger(__name__)


class PipelineRunner:
    """Single-consumer worker with bounded backlog to preserve conversational latency.

    ``start(session)`` binds the session pair; every submitted utterance carries that
    binding (``BoundUtterance``), so the worker never reads a live selection. ``stop``
    finishes the already-queued items with their bound pair within the timeout and
    reports every item it could not finish as dropped.
    """

    def __init__(
        self,
        pipeline: TranslationPipeline,
        on_result: Callable[[TranslationResult], None],
        on_error: Callable[[str], None],
        on_busy: Callable[[bool], None] | None = None,
        on_held: Callable[[HeldTurn], None] | None = None,
        max_pending: int = 2,
        on_event: Callable[[PipelineEvent], None] | None = None,
        *,
        report_turn_failures: bool = False,
    ) -> None:
        self.pipeline = pipeline
        self.on_result = on_result
        self.on_error = on_error
        self.on_busy = on_busy
        self.on_held = on_held
        # Overflow and dropped turns are notice events; without a listener they are
        # reported through ``on_error`` as text, as before.
        self.on_event = on_event
        self.max_pending = max_pending
        # Listen (CAP-0170 C §7): a failed turn is a ``TURN_FAILED`` event, not ``on_error``.
        self.report_turn_failures = report_turn_failures
        self._queue: queue.Queue[BoundUtterance | None] = queue.Queue(maxsize=max_pending)
        self._thread: threading.Thread | None = None
        self._session: SessionPair | None = None
        self._accepting = False
        self._abort = threading.Event()
        # Taking an item and aborting are atomic, so every item is either started or dropped.
        self._take_lock = threading.Lock()

    @property
    def session(self) -> SessionPair | None:
        """The session pair new utterances are bound to, or ``None`` when stopped."""
        return self._session

    def start(self, session: SessionPair) -> None:
        if self._thread and self._thread.is_alive():
            raise RuntimeError("The pipeline worker is still running; stop it first")
        self._queue = queue.Queue(maxsize=self.max_pending)
        self._abort.clear()
        self._session = session
        self._accepting = True
        self._thread = threading.Thread(target=self._run, name="translation-pipeline", daemon=True)
        self._thread.start()

    def submit(self, utterance: AudioUtterance) -> None:
        session = self._session
        if not self._accepting or session is None:
            return
        self.submit_bound(bind_utterance(utterance, session))

    def submit_bound(self, item: BoundUtterance) -> None:
        """Queue an already bound item; ignored unless it belongs to the current session."""
        session = self._session
        if not self._accepting or session is None or item.session != session:
            return
        try:
            self._queue.put_nowait(item)
        except queue.Full:
            # Drop the oldest waiting utterance: stale speech is worse than a visible warning.
            dropped: BoundUtterance | None = None
            try:
                dropped = self._queue.get_nowait()
                self._queue.task_done()
                self._queue.put_nowait(item)
            except queue.Empty:
                pass
            if self.on_event is not None:
                turn_id = dropped.turn_id if dropped is not None else None
                self.on_event(PipelineEvent(PipelineEventKind.QUEUE_OVERFLOW, turn_id=turn_id))
            else:
                self.on_error("The audio queue was full; the oldest pending segment was dropped.")

    def resolve(
        self,
        held: HeldTurn,
        source: LanguageId,
        on_done: Callable[[], None] | None = None,
    ) -> threading.Thread:
        """Resolve a held turn in the background; the result arrives through ``on_result``.

        A resolved turn is then spoken on the same thread, like a processed one.

        ``on_done`` runs after every outcome (result, dropped or error).
        """

        def run() -> None:
            if self.on_busy:
                self.on_busy(True)
            try:
                result = self.pipeline.resolve(held, source)
                if result is not None:
                    self._deliver(result)
            except Exception as exc:
                LOGGER.exception("Held turn resolution failed")
                self.on_error(str(exc))
            finally:
                if self.on_busy:
                    self.on_busy(False)
                if on_done is not None:
                    on_done()

        thread = threading.Thread(target=run, name="held-turn-resolution", daemon=True)
        thread.start()
        return thread

    def stop(self, timeout: float = 10.0) -> int:
        """Stop accepting audio, finish queued items, and return how many were dropped.

        Queued items are processed with their bound pair until ``timeout``. Items not yet
        started by then are dropped and reported through ``on_error``; a turn already being
        processed completes and its result is still delivered.
        """
        self._accepting = False
        self._session = None
        thread = self._thread
        if thread is None:
            return self._drain()
        deadline = time.monotonic() + timeout
        try:
            self._queue.put(None, timeout=max(0.0, deadline - time.monotonic()))
        except queue.Full:
            pass
        thread.join(timeout=max(0.0, deadline - time.monotonic()))
        if thread.is_alive():
            with self._take_lock:
                self._abort.set()
                turn_ids = self._drain_ids()
                dropped = len(turn_ids)
            LOGGER.warning(
                "Pipeline worker did not finish within %.1f seconds; %d queued item(s) dropped",
                timeout,
                dropped,
            )
            if dropped:
                self._report_dropped(dropped, turn_ids)
            return dropped
        self._thread = None
        return 0

    def wait_idle(self, timeout: float) -> bool:
        """Join the worker; True when it has ended (at once if it already had)."""
        thread = self._thread
        if thread is None or not thread.is_alive():
            return True
        thread.join(timeout=max(0.0, timeout))
        return not thread.is_alive()

    def _report_dropped(self, dropped: int, turn_ids: tuple[UUID, ...] = ()) -> None:
        if self.on_event is not None:
            self.on_event(
                PipelineEvent(PipelineEventKind.TURNS_DROPPED, count=dropped, turn_ids=turn_ids)
            )
            return
        self.on_error(
            f"{dropped} queued speech segment(s) were not translated before the "
            "session stopped and were dropped."
        )

    def _drain(self) -> int:
        return len(self._drain_ids())

    def _drain_ids(self) -> tuple[UUID, ...]:
        dropped: list[UUID] = []
        while True:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                return tuple(dropped)
            self._queue.task_done()
            if item is not None:
                dropped.append(item.turn_id)

    def _deliver(self, result: TranslationResult) -> None:
        """Show the text first, then speak it (CAP-0167 C §5): text never waits for speech."""
        self.on_result(result)
        spoken = getattr(self.pipeline, "spoken", None)
        if spoken is not None:
            spoken.speak(result)

    def _run(self) -> None:
        while True:
            # Taking an item and ``stop``'s abort are atomic: an item taken here is started,
            # an item still queued at abort is counted in ``stop``'s dropped count. The worker
            # never drops an item on its own, so ``StopReport.dropped`` is complete. ``stop``
            # waits at most the 0.2 s poll interval for this lock.
            with self._take_lock:
                if self._abort.is_set():
                    return
                try:
                    item = self._queue.get(timeout=0.2)
                except queue.Empty:
                    continue
            try:
                if item is None:
                    return
                if self.on_busy:
                    self.on_busy(True)
                outcome = self.pipeline.process(item)
                if isinstance(outcome, HeldTurn):
                    if self.on_held:
                        self.on_held(outcome)
                elif outcome is not None:
                    self._deliver(outcome)
            except Exception as exc:
                if self.report_turn_failures and self.on_event is not None:
                    # The message stays in the local log only (CAP-0170 C §7).
                    LOGGER.warning("Turn failed (%s)", type(exc).__name__)
                    self.on_event(
                        PipelineEvent(
                            PipelineEventKind.TURN_FAILED,
                            turn_id=item.turn_id,
                            failure=classify_failure(exc),
                        )
                    )
                else:
                    LOGGER.exception("Translation pipeline failed")
                    self.on_error(str(exc))
            finally:
                if self.on_busy and item is not None:
                    self.on_busy(False)
                self._queue.task_done()
