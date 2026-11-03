"""Session lifecycle and transcript export v2 (CAP-0169 contract.md §3.1.7).

``SessionController`` locks one ``SessionPair`` for a running session: ``start`` refuses a
session whose requirements are unmet (``ModeUnavailableError``), ``change`` while running
raises ``PairLockedError``, and ``stop`` stops capture, finishes the already-queued turns
with the pair they were captured under, clears the translation context, discards every
unresolved held turn and only then unlocks.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from lianiq.languages.capabilities import CapabilityCatalog
from lianiq.languages.errors import ModeUnavailableError, PairLockedError
from lianiq.languages.modes import SessionPair
from lianiq.languages.registry import LanguagePair
from lianiq.languages.requirements import DeviceReadiness, ModeAvailability, check

if TYPE_CHECKING:
    from lianiq.conversation.routing import HeldTurn
    from lianiq.domain import TranslationResult
    from lianiq.pipeline import PipelineRunner, TranslationPipeline

TRANSCRIPT_V2_HEADER = "# lianiq transcript v2"
LOCKED_MESSAGE = "Stop the session to change language pair or mode"
STOP_FLUSH_TIMEOUT_SECONDS = 10.0


class CaptureControl(Protocol):
    def start(self) -> None: ...

    def stop(self) -> None: ...


@dataclass(frozen=True, slots=True)
class StopReport:
    """What ``SessionController.stop`` could not keep."""

    dropped: int  # queued turns not finished within the flush timeout
    discarded: tuple[HeldTurn, ...]  # unresolved held turns, by capture time


class SessionController:
    """Owns ``start(session)``, ``stop()`` and ``change(session)`` for one conversation."""

    def __init__(
        self,
        pipeline: TranslationPipeline,
        runner: PipelineRunner,
        *,
        devices: Callable[[], DeviceReadiness],
        catalog: CapabilityCatalog | None = None,
        capture: CaptureControl | None = None,
        flush_timeout: float = STOP_FLUSH_TIMEOUT_SECONDS,
    ) -> None:
        catalog = catalog if catalog is not None else pipeline.catalog
        if catalog is None:
            raise ValueError("SessionController needs a capability catalog to gate start")
        self.pipeline = pipeline
        self.runner = runner
        self.catalog = catalog
        self.devices = devices
        self.capture = capture
        self.flush_timeout = flush_timeout
        self._session: SessionPair | None = None
        self._running = False

    @property
    def running(self) -> bool:
        return self._running

    @property
    def session(self) -> SessionPair | None:
        """The running session, or the last started or changed one while stopped."""
        return self._session

    def availability(self, session: SessionPair) -> ModeAvailability:
        return check(session, self.catalog, self.devices())

    def start(self, session: SessionPair) -> None:
        """Lock ``session`` and start the worker and capture; nothing starts if unavailable."""
        if self._running:
            raise PairLockedError(LOCKED_MESSAGE)
        availability = self.availability(session)
        if not availability.available:
            raise ModeUnavailableError(availability.missing)
        self._select(session)
        self.runner.start(session)
        if self.capture is not None:
            try:
                self.capture.start()
            except Exception:
                self.runner.stop(timeout=self.flush_timeout)
                raise
        self._running = True

    def change(self, session: SessionPair) -> ModeAvailability:
        """Select the next session while stopped; a running session is locked."""
        if self._running:
            raise PairLockedError(LOCKED_MESSAGE)
        self._select(session)
        return self.availability(session)

    def stop(self) -> StopReport:
        """Stop capture, flush queued turns with their bound pair, reset context, unlock.

        The reset, the discard of held turns (releasing their audio) and the unlock run
        even if stopping capture or the worker fails; that error is re-raised afterwards.
        """
        dropped = 0
        try:
            try:
                if self.capture is not None:
                    self.capture.stop()
            finally:
                dropped = self.runner.stop(timeout=self.flush_timeout)
        finally:
            self.pipeline.reset_context()
            discarded = self.pipeline.discard_held()
            self._running = False
        return StopReport(dropped=dropped, discarded=discarded)

    def _select(self, session: SessionPair) -> None:
        if session != self._session:
            # The context of one pair or mode never feeds another.
            self.pipeline.reset_context()
        self._session = session


def format_transcript_v2(pair: LanguagePair, results: Iterable[TranslationResult]) -> str:
    """Export v2: every turn keeps the language IDs it was translated with.

    Lines come from the immutable results ordered by ``captured_at``, so a held turn
    resolved later still appears at its capture time. The first turn follows the header
    directly (contract.md §3.1.7); later turns are separated by a blank line.
    """
    lines = [TRANSCRIPT_V2_HEADER, f"# pair: {pair.first} {pair.second}"]
    for index, result in enumerate(sorted(results, key=_captured_at)):
        timestamp = result.captured_at.isoformat(timespec="seconds")
        lines += [""] if index else []
        lines += [
            f"[{timestamp}] {result.source_language} -> {result.target_language}",
            f"{result.source_language}: {result.source_text}",
            f"{result.target_language}: {result.translated_text}",
        ]
    return "\n".join(lines) + "\n"


def _captured_at(result: TranslationResult):
    return result.captured_at
