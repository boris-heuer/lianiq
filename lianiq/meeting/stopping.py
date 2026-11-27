"""``MeetingController.stop`` and its report (CAP-0177 contract.md §5; file-size split).

Qt-free ``MeetingController`` base. ``stop`` stops both captures, lets the worker drain the
queued and in-flight contributions, then publishes ``STOPPED`` with a ``MeetingStopResult``.
It waits at most ``timeout`` seconds, then aborts the worker and waits ``grace`` seconds
more. The contributions still queued are withdrawn as ``NOT_FINISHED`` (their placeholders
stay, not translated) and, while the worker still hangs in one, that one counts too
(session-status-truthfulness §2.2.4). ``worker_alive`` is the probe for the owner's
lingering guard; ``unfinished`` the count the page shows while the meeting drains.
"""

from __future__ import annotations

import logging

from lianiq.meeting.contracts import MeetingRole
from lianiq.meeting.events import MeetingEvent, MeetingEventKind, MeetingStopResult

LOGGER = logging.getLogger("lianiq.meeting.controller")
CAPTURE_ORDER = (MeetingRole.TABLE_CAPTURE, MeetingRole.USER_CAPTURE)


class MeetingStopping:
    """``MeetingController`` base: the drain, its bound and its result."""

    def stop(self, timeout: float = 120.0, grace: float = 2.0) -> MeetingStopResult:
        """Stop both captures, drain the queue, publish ``STOPPED``; falsy on a timeout."""
        worker = self._worker
        if worker is None:
            return MeetingStopResult()
        for role in CAPTURE_ORDER:  # a failing stop must not keep the other input open
            try:
                self._captures[role].stop()
            except Exception as exc:  # noqa: BLE001 - external capture adapter boundary.
                LOGGER.error(
                    "Meeting capture stop failed: role=%s %s", role.value, type(exc).__name__
                )
        self._stopping.set()
        worker.join(timeout)
        in_flight = 0
        if worker.is_alive():
            self._abort.set()
            worker.join(grace)
            self._abandon_queue()  # the worker may still hang in one contribution
            current = self._current
            if worker.is_alive() and current is not None:
                in_flight = 1
                self._not_finished(current)
        with self._lock:
            not_finished = self._abandoned + in_flight
        result = MeetingStopResult(not_finished, not_finished > 0 or worker.is_alive())
        self._worker = None
        self._publish(MeetingEvent(MeetingEventKind.STOPPED, stop=result))
        if self._generation is not None:
            self.owner.mark_idle(self._generation)
        return result

    def unfinished(self) -> int:
        """The contributions queued or in flight (the page's draining count)."""
        return len(self._queue) + (self._current is not None)

    def worker_alive(self) -> bool:
        """The inference worker of this meeting still runs (the lingering-guard probe)."""
        worker = self._last_worker
        return worker is not None and worker.is_alive()
