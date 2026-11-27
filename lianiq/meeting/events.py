"""Meeting controller events, lines, options and engines (CAP-0177 contract.md §5).

Qt-free. ``MeetingController`` publishes ``MeetingEvent``s from its capture and inference
threads; the UI hands them to the GUI thread through the ``UiBridge`` pattern. No event
carries table-language text or audio: a ``LINE`` carries a ``MeetingLine`` whose text is
always in the local language, and an ``IGNORED`` event only carries the input's counter.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from lianiq.languages.registry import LanguageId
from lianiq.meeting.contracts import MeetingRole, TableInputDuringOutput
from lianiq.pipeline_types import PcmSynthesizer, SpeechRecognizer, Translator


class MeetingEventKind(StrEnum):
    LISTENING = "listening"
    MUTED = "muted"
    UNMUTED = "unmuted"
    PENDING = "pending"  # a table contribution was queued ("Translating…")
    LINE = "line"  # a running-view line (MeetingLine)
    WITHDRAWN = "withdrawn"  # a pending placeholder was discarded
    IGNORED = "ignored"  # other-language contribution on an input (counter only)
    FALLING_BEHIND = "falling_behind"
    CAUGHT_UP = "caught_up"
    ENDPOINT_LOST = "endpoint_lost"
    NOT_FINISHED = "not_finished"  # the stop bound passed; the placeholder stays, not translated
    STOPPED = "stopped"


@dataclass(frozen=True, slots=True)
class MeetingLine:
    contribution_id: UUID
    role: MeetingRole  # TABLE_CAPTURE: translated text; USER_CAPTURE: recognised text
    text: str  # always in the local language
    ended_at: datetime


@dataclass(frozen=True, slots=True)
class MeetingStopResult:
    """What ``MeetingController.stop`` reports (session-status-truthfulness §2.2.4).

    ``not_finished`` counts the contributions withdrawn at the bound plus the one still in
    flight; ``timed_out`` is true when any was. Truthy for a clean drain.
    """

    not_finished: int = 0
    timed_out: bool = False

    def __bool__(self) -> bool:
        return not self.timed_out


@dataclass(frozen=True, slots=True)
class MeetingEvent:
    """One controller event; the fields a kind does not use stay ``None`` or 0.

    * ``LISTENING``, ``UNMUTED``: ``role`` is the capture that listens again.
    * ``MUTED``: ``role`` is the muted capture, ``language`` the language being spoken.
    * ``PENDING``, ``WITHDRAWN``, ``NOT_FINISHED``: ``role`` and ``contribution_id`` of the
      table contribution.
    * ``LINE``: ``role``, ``contribution_id`` and ``line``.
    * ``IGNORED``: ``role`` and ``count``, the input's ignored counter after the increment.
    * ``ENDPOINT_LOST``: ``role`` is the lost capture or render role.
    * ``FALLING_BEHIND``, ``CAUGHT_UP``: ``count`` is the queue length.
    * ``STOPPED``: ``stop`` is the controller's ``MeetingStopResult``.

    ``generation`` is the owner generation of the controller's meeting; the page drops
    events of another generation (session-status-truthfulness AC-18).
    """

    kind: MeetingEventKind
    role: MeetingRole | None = None
    contribution_id: UUID | None = None
    line: MeetingLine | None = None
    language: LanguageId | None = None
    count: int = 0
    generation: int = 0
    stop: MeetingStopResult | None = None


@dataclass(frozen=True, slots=True)
class MeetingOptions:
    speak_local: bool
    table_input_during_output: TableInputDuringOutput
    guard_tail_ms: int
    max_playback_defer_ms: int


@dataclass(frozen=True, slots=True)
class SharedEngines:
    """The recogniser, translator and synthesiser, loaded once and shared with other modes.

    The meeting synthesises in memory only (``PcmSynthesizer.synthesize_pcm``).
    """

    recognizer: SpeechRecognizer
    translator: Translator
    synthesizer: PcmSynthesizer
