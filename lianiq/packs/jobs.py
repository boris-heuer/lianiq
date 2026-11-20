"""Pack jobs (CAP-0171 contract.md §5 ``JobPhase``/``CancelToken``, §6 runner). Qt-free.

``JobPhase``, ``JobView`` and ``CancelToken`` live here rather than in ``installer.py`` so that
``state.py`` and ``sources.py`` need no installer import. ``PackJobRunner`` runs one job at a
time on an executor; listener calls arrive on the worker thread, and the UI hands them to
the Qt thread through its ``UiBridge``. Logs name only pack id, version, operation, phase,
state and error class (AC-27).
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import Executor
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Literal, Protocol

from lianiq.packs.errors import (
    ConnectionUnavailable,
    InstallCancelled,
    InsufficientSpace,
    JobBusy,
    PackError,
)

if TYPE_CHECKING:
    from lianiq.packs.catalog import PackDefinition
    from lianiq.packs.installer import InstallResult, PackInstaller
    from lianiq.packs.sources import DownloadSource, ImportSource

_LOG = logging.getLogger("lianiq.packs.jobs")
OPERATIONS = ("install", "update", "remove")
PROGRESS_INTERVAL = 0.1  # seconds: at most ten progress calls per second
JOB_CANCELLED = "cancelled"
NO_CONNECTION = "no connection to {host}"
NO_SPACE = "not enough disk space"
UNEXPECTED = "unexpected error: {name}"


class JobPhase(StrEnum):
    TRANSFER = "transfer"
    CHECK = "check"
    SWAP = "swap"


@dataclass(frozen=True, slots=True)
class JobView:
    pack_id: str
    operation: Literal["install", "update", "remove"]
    phase: JobPhase
    done: int  # bytes or files done in this phase
    total: int


ProgressCallback = Callable[[JobPhase, int, int], None]  # phase, done, total


class CancelToken:
    """Set once by the UI thread, read between blocks and moves by the job."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()


class JobListener(Protocol):
    def progress(self, view: JobView) -> None: ...  # throttled to <= 10 per second

    def finished(self, result: InstallResult | None) -> None: ...  # None after a remove

    def failed(self, pack_id: str, reason: str) -> None: ...


Guard = Callable[["PackDefinition", str], None]  # raises PackInUse for a protected pack


def failure_reason(error: BaseException) -> str:
    """The text a listener shows; never a path, URL or exception message of a library."""
    if isinstance(error, InstallCancelled):
        return JOB_CANCELLED
    if isinstance(error, ConnectionUnavailable):
        return NO_CONNECTION.format(host=error.host)
    if isinstance(error, InsufficientSpace):
        return NO_SPACE
    reason = getattr(error, "reason", None)
    if isinstance(error, PackError) and isinstance(reason, str):
        return reason
    if isinstance(error, PackError):
        return str(error)
    return UNEXPECTED.format(name=error.__class__.__name__)


class PackJobRunner:
    def __init__(
        self,
        installer: PackInstaller,
        executor: Executor,
        *,
        guard: Guard | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._installer = installer
        self._executor = executor
        self._guard = guard
        self._monotonic = monotonic
        self._lock = threading.Lock()
        self._current: JobView | None = None
        self._cancel: CancelToken | None = None
        self.last_error: Exception | None = None  # the last job's error, e.g. for its host

    @property
    def current(self) -> JobView | None:
        return self._current

    def start(
        self,
        pack: PackDefinition,
        operation: str,
        source: DownloadSource | ImportSource | None,
        licence_accepted_at: datetime | None,
        listener: JobListener,
    ) -> None:
        """Start a job; ``JobBusy``, ``PackInUse`` or ``InsufficientSpace`` stop it first."""
        if operation not in OPERATIONS:
            raise ValueError(f"Unknown pack operation: {operation!r}")
        if operation != "remove" and source is None:
            raise ValueError(f"A pack {operation} needs a source")
        with self._lock:
            if self._current is not None:
                raise JobBusy()
            if self._guard is not None:
                self._guard(pack, operation)
            if operation != "remove":
                self._installer.check_space(pack)
            phase = JobPhase.SWAP if operation == "remove" else JobPhase.TRANSFER
            self._current = JobView(pack.id, operation, phase, 0, 0)  # type: ignore[arg-type]
            self._cancel = CancelToken()
            cancel = self._cancel
        try:
            self._executor.submit(
                self._run, pack, operation, source, licence_accepted_at, listener, cancel
            )
        except BaseException:
            with self._lock:  # never answer JobBusy for a job that was not scheduled
                self._current = None
                self._cancel = None
            raise
        self._log(pack, operation, phase, "started")

    def cancel(self) -> None:
        token = self._cancel
        if token is not None:
            token.cancel()

    def _run(
        self,
        pack: PackDefinition,
        operation: str,
        source: DownloadSource | ImportSource | None,
        accepted: datetime | None,
        listener: JobListener,
        cancel: CancelToken,
    ) -> None:
        last: list[float] = []

        def progress(phase: JobPhase, done: int, total: int) -> None:
            view = JobView(pack.id, operation, phase, done, total)  # type: ignore[arg-type]
            self._current = view
            now = self._monotonic()
            if not last or now - last[0] >= PROGRESS_INTERVAL:
                last[:] = [now]
                listener.progress(view)

        try:
            if operation == "remove":
                self._installer.remove(pack)
                result = None
            else:
                assert source is not None
                result = self._installer.install(pack, source, accepted, progress, cancel)
        except Exception as error:  # noqa: BLE001 - every failure reaches the listener
            phase = self._current.phase if self._current is not None else JobPhase.TRANSFER
            self._finish(error)
            self._log(pack, operation, phase, "failed", error)
            listener.failed(pack.id, failure_reason(error))
            return
        phase = self._current.phase if self._current is not None else JobPhase.SWAP
        self._finish(None)
        self._log(pack, operation, phase, "succeeded")
        listener.finished(result)

    def _finish(self, error: Exception | None) -> None:
        with self._lock:
            self.last_error = error
            self._current = None
            self._cancel = None

    @staticmethod
    def _log(
        pack: PackDefinition,
        operation: str,
        phase: JobPhase,
        state: str,
        error: Exception | None = None,
    ) -> None:
        fields = (
            f"pack_id={pack.id} version={pack.version} operation={operation} "
            f"phase={phase.value} state={state}"
        )
        if error is not None:
            fields += f" error={error.__class__.__name__}"
        _LOG.info("pack job %s", fields)
