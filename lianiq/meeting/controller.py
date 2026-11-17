"""The meeting controller: two inputs, one inference worker (CAP-0177 contract.md §5).

Qt-free. ``start`` asks the ``ActiveSessionOwner`` for the session as
``WorkspaceId.MEETING`` before any stream opens, then opens the table and the PO capture, each
an ``EndpointCaptureStream`` with its own ``UtteranceSegmenter`` (``MeetingCapture``). Every
contribution enters one no-drop ``TurnQueue`` ordered by speech end; one worker thread runs
STT → MT → TTS → playback for each, serialised, with one ``EndpointPlaybackStream`` per
render endpoint and the cross-device ``FeedbackGuard`` around every playback.

``stop`` stops both captures, lets the worker drain the queued and in-flight contributions,
then publishes ``STOPPED``. The worker never blocks forever on ``TurnQueue.take`` and ``stop``
waits at most ``timeout`` seconds; after that the remaining contributions are withdrawn.

Endpoint loss follows ``call_bridge/controller.py``: the lost capture stops or the lost
render is skipped, ``ENDPOINT_LOST`` names the role, no other device is opened and queued
contributions still finish (a lost table render skips the table-language speech; the text
stays in ``results``). ``publish`` is called from the capture and worker threads; the UI
hands events to the GUI thread (``UiBridge``). ``start``, ``stop``, ``endpoint_lost`` and
``reconcile_endpoints`` are called on the GUI thread, like the owner.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Mapping
from datetime import datetime
from functools import partial
from types import MappingProxyType
from uuid import uuid4

from lianiq.audio.capture_stream import StreamFactory
from lianiq.audio.endpoints import EndpointInventory
from lianiq.audio.playback_stream import EndpointPlaybackStream
from lianiq.call_bridge.contracts import AudioEndpointRef
from lianiq.config import AudioConfig
from lianiq.domain import AudioUtterance, TranslationResult
from lianiq.languages.errors import UnsupportedModeError
from lianiq.languages.modes import SessionPair
from lianiq.meeting.capture import MeetingCapture
from lianiq.meeting.contracts import (
    CAPTURE_ROLES,
    EndpointConflict,
    MeetingEndpoints,
    MeetingRole,
    endpoint_conflicts,
)
from lianiq.meeting.events import (
    MeetingEvent,
    MeetingEventKind,
    MeetingLine,
    MeetingOptions,
    SharedEngines,
)
from lianiq.meeting.feedback_guard import FeedbackGuard
from lianiq.meeting.language_gate import LanguageGate
from lianiq.meeting.processing import ContributionProcessing
from lianiq.meeting.turn_queue import Contribution, TurnQueue
from lianiq.pipeline_types import DEFAULT_DETECTION_MIN_PROBABILITY
from lianiq.ui.shell.session_owner import ActiveSessionOwner
from lianiq.ui.shell.workspaces import WorkspaceId

__all__ = [
    "MeetingController",
    "MeetingEvent",
    "MeetingEventKind",
    "MeetingLine",
    "MeetingOptions",
    "SharedEngines",
]

LOGGER = logging.getLogger(__name__)
_CAPTURE_ORDER = (MeetingRole.TABLE_CAPTURE, MeetingRole.USER_CAPTURE)


def _now() -> datetime:
    return datetime.now().astimezone()


class MeetingController(ContributionProcessing):
    def __init__(
        self,
        session: SessionPair,
        endpoints: MeetingEndpoints,
        options: MeetingOptions,
        engines: SharedEngines,
        owner: ActiveSessionOwner,
        publish: Callable[[MeetingEvent], None],
        clock: Callable[[], float] = time.monotonic,
        *,
        audio: AudioConfig | None = None,
        detection_min_probability: float = DEFAULT_DETECTION_MIN_PROBABILITY,
        stream_factory: StreamFactory | None = None,
        playback_factory: Callable[..., EndpointPlaybackStream] = EndpointPlaybackStream,
        wall_clock: Callable[[], datetime] = _now,
    ) -> None:
        if not session.mode.meeting or session.local_language is None:
            raise UnsupportedModeError("A meeting needs a Meeting session with a local language")
        conflicts = endpoint_conflicts(endpoints)
        if EndpointConflict.USER_IS_TABLE in conflicts:
            raise ValueError("Your microphone is the table microphone")
        local_ok = endpoints.local_render is not None
        local_ok = local_ok and EndpointConflict.LOCAL_IS_TABLE not in conflicts
        if options.speak_local and not local_ok:
            raise ValueError("Local-language speech needs its own output, not the table speaker")
        self.session, self.endpoints, self.options = session, endpoints, options
        self.engines, self.owner, self._publish_event = engines, owner, publish
        self._clock, self._wall_clock = clock, wall_clock
        self.local_language = session.local_language
        self.table_language = session.pair.other(self.local_language)
        self._languages = {
            MeetingRole.TABLE_CAPTURE: (self.table_language, self.local_language),
            MeetingRole.USER_CAPTURE: (self.local_language, self.table_language),
        }
        self._gates = {
            role: LanguageGate(source, session.pair, detection_min_probability)
            for role, (source, _target) in self._languages.items()
        }
        self._guard = FeedbackGuard(
            options.table_input_during_output,
            endpoints.local_render_is_headset,
            options.guard_tail_ms,
            options.max_playback_defer_ms,
            clock,
        )
        self._queue = TurnQueue()
        audio = audio or AudioConfig()
        capture_endpoints = {
            MeetingRole.TABLE_CAPTURE: endpoints.table_capture,
            MeetingRole.USER_CAPTURE: endpoints.user_capture,
        }
        self._captures = {
            role: MeetingCapture(
                capture_endpoints[role],
                audio,
                partial(self._on_utterance, role),
                is_muted=partial(self._guard.is_muted, role),
                on_unmuted=partial(self._publish, MeetingEvent(MeetingEventKind.UNMUTED, role)),
                stream_factory=stream_factory,
            )
            for role in _CAPTURE_ORDER
        }
        render_endpoints = {MeetingRole.TABLE_RENDER: endpoints.table_render}
        if local_ok:
            render_endpoints[MeetingRole.LOCAL_RENDER] = endpoints.local_render
        self._renders = {
            role: playback_factory(endpoint, on_playback_state=partial(self._playback_state, role))
            for role, endpoint in render_endpoints.items()
        }
        self._speak_local = options.speak_local
        self._lock = threading.Lock()
        self._results: list[TranslationResult] = []
        self._ignored = dict.fromkeys(_CAPTURE_ORDER, 0)
        self._lost: set[MeetingRole] = set()
        self._behind = False
        self._stopping = threading.Event()
        self._abort = threading.Event()
        self._worker: threading.Thread | None = None
        self._generation: int | None = None
        owner.register(WorkspaceId.MEETING, self.stop)

    @property
    def results(self) -> tuple[TranslationResult, ...]:
        """The translated contributions only, ordered by speech end (``captured_at``)."""
        with self._lock:
            return tuple(sorted(self._results, key=lambda result: result.captured_at))

    @property
    def running(self) -> bool:
        return self._worker is not None

    @property
    def lost_roles(self) -> frozenset[MeetingRole]:
        with self._lock:
            return frozenset(self._lost)

    @property
    def captures(self) -> Mapping[MeetingRole, MeetingCapture]:
        """The two inputs by capture role (level meters and synthetic test adapters)."""
        return MappingProxyType(self._captures)

    def start(self) -> None:
        """Take the session as ``WorkspaceId.MEETING``, open both captures and the worker."""
        if self._worker is not None or self._generation is not None:
            raise RuntimeError("A meeting controller runs one meeting")
        generation = self.owner.request_start(WorkspaceId.MEETING)  # raises SessionBusy
        started: list[MeetingCapture] = []
        try:
            for role in _CAPTURE_ORDER:
                self._captures[role].start()
                started.append(self._captures[role])
        except Exception:
            for capture in reversed(started):
                capture.stop()
            self.owner.mark_idle(generation)
            raise
        self._generation = generation
        self._worker = threading.Thread(target=self._run, name="meeting-inference", daemon=True)
        self._worker.start()
        self.owner.mark_running(generation)
        for role in _CAPTURE_ORDER:
            self._publish(MeetingEvent(MeetingEventKind.LISTENING, role))

    def set_speak_local(self, on: bool) -> None:
        """Switch local-language speech for table contributions; allowed while running."""
        if on and MeetingRole.LOCAL_RENDER not in self._renders:
            raise ValueError("Local-language speech needs its own output, not the table speaker")
        self._speak_local = on

    def stop(self, timeout: float = 120.0) -> bool:
        """Stop both captures, drain the queue, publish ``STOPPED``; ``False`` on a timeout."""
        worker = self._worker
        if worker is None:
            return True
        for role in _CAPTURE_ORDER:  # a failing stop must not keep the other input open
            try:
                self._captures[role].stop()
            except Exception as exc:  # noqa: BLE001 - external capture adapter boundary.
                LOGGER.error(
                    "Meeting capture stop failed: role=%s %s", role.value, type(exc).__name__
                )
        self._stopping.set()
        worker.join(timeout)
        drained = not worker.is_alive()
        if not drained:
            self._abort.set()
            worker.join(2.0)
        self._worker = None
        self._publish(MeetingEvent(MeetingEventKind.STOPPED))
        if self._generation is not None:
            self.owner.mark_idle(self._generation)
        return drained

    def endpoint_lost(self, role: MeetingRole) -> None:
        """Stop the lost capture or skip the lost render; no other device is opened."""
        with self._lock:
            if role in self._lost:
                return
            self._lost.add(role)
        if role in CAPTURE_ROLES:
            self._captures[role].stop()
        LOGGER.warning("Meeting endpoint lost: role=%s", role.value)
        self._publish(MeetingEvent(MeetingEventKind.ENDPOINT_LOST, role))

    def reconcile_endpoints(self, inventory: EndpointInventory) -> None:
        """Report every assigned endpoint missing from ``inventory`` as lost (by identity)."""
        for role, endpoint in self._assigned().items():
            try:
                inventory.resolve(endpoint.endpoint_id, endpoint.flow)
            except LookupError:
                self.endpoint_lost(role)

    def _assigned(self) -> dict[MeetingRole, AudioEndpointRef]:
        assigned = {
            MeetingRole.TABLE_CAPTURE: self.endpoints.table_capture,
            MeetingRole.TABLE_RENDER: self.endpoints.table_render,
            MeetingRole.USER_CAPTURE: self.endpoints.user_capture,
        }
        if MeetingRole.LOCAL_RENDER in self._renders:
            assigned[MeetingRole.LOCAL_RENDER] = self.endpoints.local_render
        return assigned

    def _on_utterance(self, role: MeetingRole, utterance: AudioUtterance) -> None:
        source, target = self._languages[role]
        item = Contribution(uuid4(), role, source, target, self._wall_clock(), utterance)
        self._queue.put(item)
        if role is MeetingRole.TABLE_CAPTURE:
            self._publish(
                MeetingEvent(MeetingEventKind.PENDING, role, contribution_id=item.contribution_id)
            )
        self._check_backlog()

    def _publish(self, event: MeetingEvent) -> None:
        self._publish_event(event)
