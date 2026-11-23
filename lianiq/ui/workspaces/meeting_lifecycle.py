"""Start, stop and events of ``MeetingWorkspace`` (CAP-0177 WI-04; file-size split).

The controller is built here, only at Start, after the models are prepared; its ``stop()``
runs on a worker thread (see ``meeting.py``). ``_ControllerOwner`` is the session owner as
the controller sees it. Its events reach ``running_event`` (``meeting_running``) on the GUI
thread; ``STOPPED`` ends the page's meeting, then offers the end-of-meeting dialog
(``meeting_notices``).
"""

from __future__ import annotations

import logging
import threading
from functools import partial

from PySide6.QtCore import Signal, Slot

from lianiq.meeting.contracts import TableInputDuringOutput
from lianiq.meeting.events import MeetingEvent, MeetingEventKind, MeetingOptions
from lianiq.packs.protection import ActiveUsage
from lianiq.ui import notice_catalog as catalog
from lianiq.ui import strings
from lianiq.ui.shell.session_owner import ActiveSessionOwner, SessionBusy
from lianiq.ui.shell.workspaces import WorkspaceId
from lianiq.ui.workspaces.meeting_notices import keys_resolved_by_meeting_start

MEETING = WorkspaceId.MEETING
LOGGER = logging.getLogger(__name__)


class _ControllerOwner:
    """The ``ActiveSessionOwner`` as the controller sees it (see the module docstring)."""

    def __init__(self, owner: ActiveSessionOwner, generation: int, idle: Signal) -> None:
        self._owner, self._generation, self._idle = owner, generation, idle

    def register(self, _mode: WorkspaceId, _stopper) -> None:
        """The page registered its own non-blocking stopper once; keep it."""

    def request_start(self, _mode: WorkspaceId) -> int:
        return self._generation  # reserved by the page before the models loaded

    def mark_running(self, generation: int) -> None:
        self._owner.mark_running(generation)

    def mark_idle(self, generation: int) -> None:
        self._idle.emit(generation)  # queued to the GUI thread when called by ``stop``


class _ModelsFailed(Exception):
    pass


class _NoController(Exception):
    pass


class MeetingLifecycle:
    """``MeetingWorkspace`` base: **Start meeting**, the models, the controller and stop."""

    @Slot()
    def start_meeting(self) -> None:
        if self.active() or self.stopping:
            return
        busy = self.owner.busy_for(MEETING)
        if busy is not None:  # nothing is opened; the running session continues
            self.host.show_busy(MEETING, busy)
            return
        try:
            session = self.session()
            availability = self.availability()
        except Exception as exc:  # noqa: BLE001 - GUI boundary reports invalid settings.
            self.host.show_error(str(exc), MEETING)
            return
        if not availability.available:  # a device changed since the last refresh
            title = self.missing_text(availability.missing)
            where = catalog.source(MEETING)
            self.host.post_notice(
                catalog.mode_unavailable(MEETING, title, where, self.start_meeting)
            )
            self.refresh()
            return
        try:
            self._generation = self.owner.request_start(MEETING)
        except SessionBusy as refused:
            self.host.show_busy(MEETING, refused.active)
            return
        local_speech = self.speak_local_checkbox.isChecked()
        self.host.usage_tracker.bind(ActiveUsage(MEETING, session, local_speech))
        self.starting, self._pending = True, session
        self.refresh()
        self.state_label.setText(strings.SESSION_STARTING.format(mode=strings.NAV_MEETING))
        self.host.prepare_in_background(session, self.models_ready)

    @Slot(int, bool, str)
    def _models_ready(self, generation: int, ready: bool, message: str) -> None:
        if not self.starting or generation != self.host.start_generation:
            return  # a cancelled start
        self.starting = False
        session, self._pending = self._pending, None
        where = catalog.source(MEETING)
        try:
            if not ready:
                raise _ModelsFailed(message)
            factory = self.host.meeting_factory
            if factory is None:
                raise _NoController
            self.controller = factory(
                session,
                self.meeting_endpoints(),
                self._options(),
                _ControllerOwner(self.owner, self._generation, self.owner_idle),
                self.meeting_event.emit,
            )
            for role, capture in self.controller.captures.items():  # the strip's level bars
                capture.on_level = partial(self.meeting_level.emit, role)
            self.reset_running(running=True)
            self.controller.start()
        except _NoController:
            reason = strings.MEETING_NO_CONTROLLER
            self._start_failed(catalog.start_failed(MEETING, reason, where, self.start_meeting))
        except _ModelsFailed as exc:
            self._start_failed(catalog.model_failed(MEETING, str(exc), where, self.start_meeting))
        except Exception as exc:  # noqa: BLE001 - GUI boundary reports setup failures.
            self._start_failed(catalog.start_failed(MEETING, str(exc), where, self.start_meeting))
        else:
            self.host.resolve_notices(catalog.keys_resolved_by_start(MEETING))
            self.host.resolve_notices(keys_resolved_by_meeting_start())
            self.refresh()
            self.state_label.setText(strings.SESSION_RUNNING.format(mode=strings.NAV_MEETING))

    def _options(self) -> MeetingOptions:
        meeting = self.config.meeting
        return MeetingOptions(
            self.speak_local_checkbox.isChecked(),
            TableInputDuringOutput(meeting.table_input_during_output),
            meeting.guard_tail_ms,
            meeting.max_playback_defer_ms,
        )

    def _start_failed(self, notice) -> None:
        self.controller = None
        self.owner.mark_idle(self._generation)
        self.reset_running(running=False)
        self.host.post_notice(notice)
        self.refresh()

    @Slot()
    def end_meeting(self) -> None:
        """**End meeting**: the same as **Stop (F9)** while the meeting holds the session."""
        if self.owner.active is MEETING:
            self.owner.stop()
        else:
            self.stop_meeting()

    @Slot()
    def stop_meeting(self) -> None:
        """The owner's stopper: never blocks; the controller drains on a worker thread."""
        if self.starting:
            self.starting, self._pending = False, None
            if self.owner.active is MEETING:
                self.owner.mark_idle(self._generation)
            self.refresh()
            return
        controller = self.controller
        if self.stopping:
            return
        if controller is None:  # nothing runs: end a session the owner still records
            if self.owner.active is MEETING:
                self.owner.mark_idle(self._generation)
            return
        self.stopping = True
        threading.Thread(
            target=_drain,
            args=(controller, self.meeting_event.emit),
            name="meeting-stop",
            daemon=True,
        ).start()

    @Slot(object)
    def _event(self, event) -> None:
        if event.kind is not MeetingEventKind.STOPPED:
            if self.controller is not None:  # a late event of an ended meeting is ignored
                self.running_event(event)
            return
        controller = self.controller
        self.controller, self.stopping = None, False
        self.owner.mark_idle(self._generation)  # drained: other modes may start now
        self.reset_running(running=False)
        self.refresh()
        self.host.conversation.refresh_availability()
        if controller is not None:  # after the drain: the end-of-meeting dialog (WI-05)
            self.meeting_ended(controller)


def _drain(controller, publish) -> None:
    """``controller.stop()`` on the stopping thread; a failure still ends the page's meeting."""
    try:
        controller.stop()
    except Exception as exc:  # noqa: BLE001 - worker boundary: the type only, no transcript
        LOGGER.error("The meeting did not stop cleanly: %s", type(exc).__name__)
        publish(MeetingEvent(MeetingEventKind.STOPPED))
