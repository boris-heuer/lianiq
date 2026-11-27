"""The Listen stop policy (CAP-0170 contract.md §6; session-status-truthfulness §2.2.2).

``ListenController`` base (file-size split). The owner calls ``_begin_stop``: capture stops on
the GUI thread, the ``listen-stop`` thread runs ``SessionController.stop`` (the flush bound)
and then waits the inference grace. A worker still alive after the grace is a timeout: the
``ListenStopResult`` carries the not-finished count (the dropped turns plus the in-flight one)
and the worker's ``alive`` probe; ``_finish`` registers it with ``owner.linger`` so every Start
is refused while it lives, and notifies ``STOP_TIMEOUT``. Late output is dropped by generation.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from lianiq.listen.lifecycle import (
    LISTEN,
    SHUTDOWN_FLUSH_SECONDS,
    AlertKind,
    ListenAlert,
    ListenPhase,
    quietly,
)

if TYPE_CHECKING:
    from lianiq.languages.session import SessionController

LOGGER = logging.getLogger("lianiq.listen.controller")


def _ended() -> bool:
    return False


@dataclass(frozen=True, slots=True)
class ListenStopResult:
    """What a Listen stop could not finish."""

    not_finished: int = 0  # dropped turns plus the in-flight one of a timeout
    timed_out: bool = False  # the worker was still alive after flush bound plus grace
    alive: Callable[[], bool] = _ended  # the lingering-worker probe (``owner.linger``)


CLEAN_STOP = ListenStopResult()


class ListenStopping:
    """``ListenController`` base: ``stop``, the ``listen-stop`` thread, ``_finish``, loss."""

    def stop(self) -> None:
        """Stop from the page; the owner calls ``_begin_stop`` and stays *stopping*."""
        if self._phase in (ListenPhase.LOADING, ListenPhase.LISTENING):
            self._owner.stop()

    def _begin_stop(self) -> None:
        self._end_replay()
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
        result = CLEAN_STOP
        if controller is not None:
            dropped = 0
            try:
                dropped = controller.stop().dropped
            except Exception as error:  # noqa: BLE001 - logged by class name only
                LOGGER.warning("Listen stop failed (%s)", type(error).__name__)
            runner = controller.runner
            if not runner.wait_idle(self._grace):
                LOGGER.warning("Listen inference did not finish within the grace period")
                result = ListenStopResult(dropped + 1, True, runner.alive)
        self._post(lambda: self._finish(generation, result))

    def _finish(self, generation: int, result: ListenStopResult = CLEAN_STOP) -> None:
        if generation != self._generation or self._phase is ListenPhase.IDLE:
            return
        self._pipeline.on_recognized = None
        self._session = self._capture = None
        self._busy = False
        changed = self._transcript.finish_session(generation)
        self._phase = ListenPhase.IDLE
        self._not_finished = result.not_finished
        if result.timed_out:
            self._owner.linger(LISTEN, result.alive)  # Start refused while it lives (AC-05)
        self._owner.mark_idle(generation)
        self.render(tuple(range(len(self._transcript.rows))) if changed else ())
        if result.timed_out:
            alert = ListenAlert(AlertKind.STOP_TIMEOUT, generation, count=result.not_finished)
            self._notify(alert)
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
