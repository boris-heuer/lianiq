"""Listen lifecycle constants, phases, alerts and the page snapshot (contract.md §6)."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Protocol

from lianiq.listen.session import ListenReadiness, StartBlock
from lianiq.pipeline_types import FailureReason
from lianiq.ui.shell.workspaces import WorkspaceId

LISTEN_QUEUE_LIMIT: Final = 3  # PipelineRunner max_pending for Listen
LISTEN_STOP_FLUSH_SECONDS: Final = 10.0
LISTEN_INFERENCE_GRACE_SECONDS: Final = 30.0
SHUTDOWN_FLUSH_SECONDS: Final = 1.0
LISTEN: Final = WorkspaceId.LISTEN


class ListenPhase(StrEnum):
    IDLE = "idle"
    LOADING = "loading"
    LISTENING = "listening"
    STOPPING = "stopping"


class AlertKind(StrEnum):
    START_FAILED = "start_failed"  # model load or capture open failed
    MICROPHONE_LOST = "microphone_lost"


@dataclass(frozen=True, slots=True)
class ListenAlert:
    kind: AlertKind
    generation: int
    reason: FailureReason | None = None
    device_name: str = ""


@dataclass(frozen=True, slots=True)
class ListenSnapshot:  # rendered by the page; never holds audio
    phase: ListenPhase
    readiness: ListenReadiness
    busy: bool  # worker processing → *Processing…*
    rows_changed: tuple[int, ...]  # row indexes to refresh
    can_export: bool  # at least one DONE row
    paused: bool = False  # listening, the microphone paused while a translation is spoken


class Capture(Protocol):
    """The part of ``MicrophoneCapture`` used here."""

    device: int | None

    def start(self) -> None: ...

    def stop(self) -> None: ...

    def set_muted(self, muted: bool) -> None: ...


class UsageBinding(Protocol):
    """The part of the CAP-0171 ``ActiveUsageTracker`` used here."""

    def bind(self, usage) -> None: ...


NOT_READY = ListenReadiness(StartBlock.NONE, ())
LOGGER = logging.getLogger("lianiq.listen.controller")


def quietly(action: Callable[[], object], what: str) -> None:
    """Run a stop step; a failure is logged by class name only and never stops the rest."""
    try:
        action()
    except Exception as error:  # noqa: BLE001
        LOGGER.warning("Listen %s failed (%s)", what, type(error).__name__)
