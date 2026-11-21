"""Listen & translate lifecycle (CAP-0170 contract.md §6); Qt-free, GUI-thread API.

Rows are posted before their item reaches the worker; callbacks carry the generation and stale
ones are dropped. Notices are ``ListenAlert`` values the page maps to ``listen.*`` notices.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import TYPE_CHECKING

from lianiq.languages.requirements import DeviceReadiness
from lianiq.languages.session import SessionController
from lianiq.listen.lifecycle import (
    LISTEN,
    LISTEN_INFERENCE_GRACE_SECONDS,
    LISTEN_QUEUE_LIMIT,
    LISTEN_STOP_FLUSH_SECONDS,
    NOT_READY,
    SHUTDOWN_FLUSH_SECONDS,
    AlertKind,
    Capture,
    ListenAlert,
    ListenPhase,
    ListenSnapshot,
    UsageBinding,
    quietly,
)
from lianiq.listen.session import StartBlock
from lianiq.listen.transcript import ListenTranscript, SegmentState
from lianiq.packs.protection import ActiveUsage
from lianiq.pipeline import PipelineRunner
from lianiq.pipeline_types import (
    BoundUtterance,
    FailureReason,
    PipelineEvent,
    PipelineEventKind,
    bind_utterance,
    classify_failure,
)

if TYPE_CHECKING:
    from lianiq.audio.device_selection import ResolvedDevice
    from lianiq.domain import AudioUtterance, Transcript, TranslationResult
    from lianiq.languages.modes import SessionPair
    from lianiq.listen.pipeline import ListenPipeline
    from lianiq.listen.session import ListenReadiness
    from lianiq.ui.shell.session_owner import ActiveSessionOwner

LOGGER = logging.getLogger(__name__)


class ListenController:
    def __init__(
        self,
        owner: ActiveSessionOwner,
        tracker: UsageBinding | None,
        pipeline: ListenPipeline,
        capture_factory: Callable[..., Capture],
        microphone: Callable[[], ResolvedDevice],
        post: Callable[[Callable[[], None]], None],
        render: Callable[[ListenSnapshot], None],
        notify: Callable[[ListenAlert], None],
        readiness: Callable[[SessionPair], ListenReadiness],
        *,
        flush_seconds: float = LISTEN_STOP_FLUSH_SECONDS,
        grace_seconds: float = LISTEN_INFERENCE_GRACE_SECONDS,
    ) -> None:
        self._owner, self._tracker, self._pipeline = owner, tracker, pipeline
        self._capture_factory, self._microphone = capture_factory, microphone
        self._post, self._render, self._notify = post, render, notify
        self._readiness = readiness
        self._flush, self._grace = flush_seconds, grace_seconds
        self._transcript = ListenTranscript()
        self._phase = ListenPhase.IDLE
        self._generation = 0
        self._selection: SessionPair | None = None
        self._session: SessionController | None = None
        self._capture: Capture | None = None
        self._busy = False
        self._lost: str | None = None  # device name of a microphone loss being handled
        owner.register(LISTEN, self._begin_stop, asynchronous=True)

    @property
    def phase(self) -> ListenPhase:
        return self._phase

    @property
    def transcript(self) -> ListenTranscript:
        return self._transcript

    def select(self, session: SessionPair) -> None:
        """The page's current selection; readiness is shown for it."""
        self._selection = session
        self.render()

    # Start.

    def start(self, session: SessionPair) -> None:
        self._selection = session
        if self._phase is not ListenPhase.IDLE:
            return
        if self._readiness(session).block is not StartBlock.NONE:
            self.render()
            return
        generation = self._owner.request_start(LISTEN)  # SessionBusy propagates
        self._generation, self._phase, self._lost = generation, ListenPhase.LOADING, None
        if self._tracker is not None:
            self._tracker.bind(ActiveUsage(LISTEN, session, False))
        self.render()
        threading.Thread(
            target=self._load, args=(generation, session), name="listen-load", daemon=True
        ).start()

    def _load(self, generation: int, session: SessionPair) -> None:
        try:
            self._pipeline.prepare(session)
        except Exception as error:  # noqa: BLE001 - mapped to a reason; message not shown
            LOGGER.warning("Listen model load failed (%s)", type(error).__name__)
            reason = classify_failure(error)
            self._post(lambda: self._loaded(generation, session, reason))
            return
        self._post(lambda: self._loaded(generation, session, None))

    def _loaded(self, generation: int, session: SessionPair, failure: FailureReason | None) -> None:
        if generation != self._generation or self._phase is ListenPhase.IDLE:
            return
        if self._phase is ListenPhase.STOPPING:  # stopped while loading: nothing opened
            self._finish(generation)
            return
        if failure is None:
            try:
                self._open(generation, session)
            except Exception as error:  # noqa: BLE001 - capture open failure
                LOGGER.warning("Listen capture failed to start (%s)", type(error).__name__)
                failure = classify_failure(error)
        if failure is not None:
            self._session = self._capture = None
            self._finish(generation)
            self._notify(ListenAlert(AlertKind.START_FAILED, generation, failure))
            return
        self._phase = ListenPhase.LISTENING
        self._owner.mark_running(generation)
        self.render()

    def _open(self, generation: int, session: SessionPair) -> None:
        post = self._post
        runner = PipelineRunner(
            self._pipeline,
            on_result=lambda result: post(lambda: self._completed(generation, result)),
            on_error=lambda _message: None,  # turn failures arrive as TURN_FAILED events
            on_busy=lambda busy: post(lambda: self._set_busy(generation, busy)),
            max_pending=LISTEN_QUEUE_LIMIT,
            on_event=lambda event: post(lambda: self._event(generation, event)),
            report_turn_failures=True,
        )

        def on_utterance(utterance: AudioUtterance) -> None:  # audio callback thread
            item = bind_utterance(utterance, session)
            post(lambda: self._captured(generation, item))
            runner.submit_bound(item)

        def on_error(_message: str) -> None:  # audio callback thread
            post(lambda: self._capture_failed(generation))

        def on_recognized(item: BoundUtterance, transcript: Transcript) -> None:  # worker
            text = transcript.text
            post(lambda: self._recognized(generation, item, text))

        capture = self._capture_factory(on_utterance=on_utterance, on_error=on_error)
        endpoint = self._microphone().endpoint
        capture.device = None if endpoint is None else endpoint.runtime_index
        controller = SessionController(
            self._pipeline,
            runner,
            devices=lambda: DeviceReadiness(microphone=self._microphone().ready),
            capture=capture,
            flush_timeout=self._flush,
        )
        self._pipeline.on_recognized = on_recognized
        self._capture, self._session = capture, controller
        controller.start(session)

    # Stop.

    def stop(self) -> None:
        """Stop from the page; the owner calls ``_begin_stop`` and stays *stopping*."""
        if self._phase in (ListenPhase.LOADING, ListenPhase.LISTENING):
            self._owner.stop()

    def _begin_stop(self) -> None:
        if self._phase not in (ListenPhase.LOADING, ListenPhase.LISTENING):
            return
        loading = self._phase is ListenPhase.LOADING
        self._phase = ListenPhase.STOPPING
        self.render()
        if loading:
            return  # ``_loaded`` finishes the stop
        capture, controller, generation = self._capture, self._session, self._generation
        if capture is not None:
            quietly(capture.stop, "capture stop")  # no new segments
        threading.Thread(
            target=self._drain, args=(generation, controller), name="listen-stop", daemon=True
        ).start()

    def _drain(self, generation: int, controller: SessionController | None) -> None:
        if controller is not None:
            quietly(controller.stop, "stop")
            if not controller.runner.wait_idle(self._grace):
                LOGGER.warning("Listen inference did not finish within the grace period")
        self._post(lambda: self._finish(generation))

    def _finish(self, generation: int) -> None:
        if generation != self._generation or self._phase is ListenPhase.IDLE:
            return
        self._pipeline.on_recognized = None
        self._session = self._capture = None
        self._busy = False
        changed = self._transcript.finish_session(generation)
        self._phase = ListenPhase.IDLE
        self._owner.mark_idle(generation)
        self.render(tuple(range(len(self._transcript.rows))) if changed else ())
        if self._lost is not None:
            name, self._lost = self._lost, None
            self._notify(ListenAlert(AlertKind.MICROPHONE_LOST, generation, device_name=name))

    def microphone_lost(self, device_name: str) -> None:
        if self._phase in (ListenPhase.LOADING, ListenPhase.LISTENING):
            self._lost = device_name
            self.stop()

    def _capture_failed(self, generation: int) -> None:
        if generation == self._generation:
            self.microphone_lost(self._microphone().label)

    def shutdown(self) -> None:
        """Window close: stop with a one-second flush; nothing is saved."""
        if self._phase is ListenPhase.IDLE:
            return
        generation, controller = self._generation, self._session
        self._phase = ListenPhase.STOPPING
        if controller is not None:
            controller.flush_timeout = SHUTDOWN_FLUSH_SECONDS
            quietly(controller.stop, "shutdown stop")
        self._lost = None
        self._finish(generation)

    # Worker callbacks, on the GUI thread.

    def _current(self, generation: int) -> bool:
        return generation == self._generation and self._phase is not ListenPhase.IDLE

    def _captured(self, generation: int, item: BoundUtterance) -> None:
        if self._current(generation):
            row = self._transcript.captured(
                item.turn_id, item.captured_at, item.session, generation
            )
            self.render((row,))

    def _recognized(self, generation: int, item: BoundUtterance, text: str) -> None:
        if self._current(generation):
            self._changed(self._transcript.recognized(item.turn_id, text))

    def _completed(self, generation: int, result: TranslationResult) -> None:
        if self._current(generation):
            self._changed(self._transcript.completed(result))

    def _event(self, generation: int, event: PipelineEvent) -> None:
        if not self._current(generation):
            return
        if event.kind is PipelineEventKind.QUEUE_OVERFLOW and event.turn_id is not None:
            self._changed(self._transcript.mark(event.turn_id, SegmentState.SKIPPED))
        elif event.kind is PipelineEventKind.TURN_FAILED and event.turn_id is not None:
            self._changed(self._transcript.mark(event.turn_id, SegmentState.FAILED, event.failure))
        elif event.kind is PipelineEventKind.TURNS_DROPPED:
            rows = [
                self._transcript.mark(turn, SegmentState.NOT_FINISHED) for turn in event.turn_ids
            ]
            self.render(tuple(row for row in rows if row is not None))

    def _set_busy(self, generation: int, busy: bool) -> None:
        if self._current(generation):
            self._busy = busy
            self.render()

    def _changed(self, row: int | None) -> None:
        self.render(() if row is None else (row,))

    def render(self, rows: tuple[int, ...] = ()) -> None:
        selection = self._selection
        readiness = NOT_READY if selection is None else self._readiness(selection)
        can_export = any(row.state is SegmentState.DONE for row in self._transcript.rows)
        self._render(ListenSnapshot(self._phase, readiness, self._busy, rows, can_export))
