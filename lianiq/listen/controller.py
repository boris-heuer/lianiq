"""Listen & translate lifecycle (CAP-0170 contract.md §6); Qt-free, GUI-thread API.

Rows are posted before their item reaches the worker; callbacks carry the generation and stale
ones are dropped. Notices are ``ListenAlert`` values the page maps to ``listen.*`` notices.
``end_replay`` ends a transcript replay (``host.pipeline.spoken``) before a Start, a Stop
and a clear; while a playback runs a listening capture is muted (``playback_changed``).
The stop policy and its timeout result live in ``stopping.py`` (file-size split).
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import TYPE_CHECKING

from lianiq.languages.requirements import DeviceReadiness
from lianiq.languages.session import SessionController
from lianiq.listen.callbacks import ListenCallbacks
from lianiq.listen.lifecycle import (
    LISTEN,
    LISTEN_INFERENCE_GRACE_SECONDS,
    LISTEN_QUEUE_LIMIT,
    LISTEN_STOP_FLUSH_SECONDS,
    NOT_READY,
    AlertKind,
    Capture,
    ListenAlert,
    ListenPhase,
    ListenSnapshot,
    UsageBinding,
)
from lianiq.listen.session import StartBlock
from lianiq.listen.stopping import ListenStopping
from lianiq.listen.transcript import ListenTranscript, SegmentState
from lianiq.packs.protection import ActiveUsage
from lianiq.pipeline import PipelineRunner
from lianiq.pipeline_types import (
    BoundUtterance,
    FailureReason,
    bind_utterance,
    classify_failure,
)

if TYPE_CHECKING:
    from lianiq.audio.device_selection import ResolvedDevice
    from lianiq.domain import AudioUtterance, Transcript
    from lianiq.languages.modes import SessionPair
    from lianiq.listen.pipeline import ListenPipeline
    from lianiq.listen.session import ListenReadiness
    from lianiq.ui.shell.session_owner import ActiveSessionOwner

LOGGER = logging.getLogger(__name__)


class ListenController(ListenStopping, ListenCallbacks):
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
        end_replay: Callable[[], None] = lambda: None,
    ) -> None:
        self._owner, self._tracker, self._pipeline = owner, tracker, pipeline
        self._capture_factory, self._microphone = capture_factory, microphone
        self._post, self._render, self._notify = post, render, notify
        self._readiness, self._end_replay = readiness, end_replay
        self._paused = False  # a playback runs (paired-transcript §3.3)
        self._flush, self._grace = flush_seconds, grace_seconds
        self._transcript = ListenTranscript()
        self._phase = ListenPhase.IDLE
        self._generation = 0
        self._selection: SessionPair | None = None
        self._session: SessionController | None = None
        self._capture: Capture | None = None
        self._busy = False
        self._lost: str | None = None  # device name of a microphone loss being handled
        self._not_finished = 0  # the last stop timed out with this many turns not finished
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
        self._end_replay()  # a replay never overlaps a session
        generation = self._owner.request_start(LISTEN)  # SessionBusy propagates
        self._generation, self._phase, self._lost = generation, ListenPhase.LOADING, None
        self._not_finished = 0
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
        if self._paused and self._capture is not None:
            self._capture.set_muted(True)  # a replay of this page is still playing
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

    def clear(self) -> None:
        """**Clear transcript**: end a playback, stop when not idle, empty the log, render."""
        self._end_replay()
        if self._phase is not ListenPhase.IDLE:
            self.stop()
        self._transcript.clear()
        self._transcript.finish_session(self._generation)  # a session without rows too
        self.render()

    def render(self, rows: tuple[int, ...] = ()) -> None:
        selection = self._selection
        readiness = NOT_READY if selection is None else self._readiness(selection)
        can_export = any(row.state is SegmentState.DONE for row in self._transcript.rows)
        paused = self._paused and self._phase is ListenPhase.LISTENING
        lost = self._not_finished if self._phase is ListenPhase.IDLE else 0
        snapshot = ListenSnapshot(
            self._phase, readiness, self._busy, rows, can_export, paused, lost
        )
        self._render(snapshot)
