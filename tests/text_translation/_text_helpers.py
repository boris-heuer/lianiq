"""Spies and a GUI-thread stand-in for the CAP-0172 text core tests."""

from __future__ import annotations

import queue
import threading
import time
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field

from lianiq.languages import BUILTIN_REGISTRY, DirectedEdge, LanguageId, LanguageRegistry
from tests.languages.synthetic import SYNTHETIC_LANGUAGES

DE = LanguageId("de")
ZH = LanguageId("zh-Hans")
DE_ZH = DirectedEdge(DE, ZH)


def three_language_registry() -> LanguageRegistry:
    """German, Mandarin and the synthetic ``qaa`` (AC-06)."""
    return LanguageRegistry(
        (BUILTIN_REGISTRY.get(DE), BUILTIN_REGISTRY.get(ZH), SYNTHETIC_LANGUAGES[0])
    )


def fake_tokens(text: str) -> int:
    """A token measure: two per non-wide word, one per wide character."""
    wide = sum(unicodedata.east_asian_width(c) in ("W", "F") for c in text)
    words = len(
        "".join(" " if unicodedata.east_asian_width(c) in ("W", "F") else c for c in text).split()
    )
    return wide + 2 * words


class GuiThread:
    """Collects callbacks posted by the worker and runs them on the test thread."""

    def __init__(self) -> None:
        self._queue: queue.Queue[Callable[[], None]] = queue.Queue()

    def post(self, callback: Callable[[], None]) -> None:
        self._queue.put(callback)

    def pump(self, until: Callable[[], bool], timeout: float = 5.0) -> None:
        deadline = time.monotonic() + timeout
        while not until():
            remaining = deadline - time.monotonic()
            assert remaining > 0, "timed out waiting for the worker"
            try:
                self._queue.get(timeout=remaining)()
            except queue.Empty:
                continue


@dataclass
class IdentitySpy:
    """Returns each segment unchanged; records calls and the largest overlap."""

    delay: float = 0.0
    measure: Callable[[str], int] | None = None
    calls: list[tuple[str, str, tuple[str, ...]]] = field(default_factory=list)
    active: int = 0
    overlap: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def translate(self, text: str, edge: DirectedEdge, context: tuple[str, ...] = ()) -> str:
        with self._lock:
            self.active += 1
            self.overlap = max(self.overlap, self.active)
            self.calls.append((text, edge.key, tuple(context)))
        try:
            if self.delay:
                time.sleep(self.delay)
            return text
        finally:
            with self._lock:
                self.active -= 1


@dataclass
class MeasuredSpy(IdentitySpy):
    """An identity spy that also offers ``token_count`` like ``MarianTranslator``."""

    def token_count(self, text: str, edge: DirectedEdge) -> int:
        return fake_tokens(text)


@dataclass
class GatedSpy(IdentitySpy):
    """Blocks every call until ``release`` and signals each entry through ``entered``."""

    gate: threading.Event = field(default_factory=threading.Event)
    entered: threading.Semaphore = field(default_factory=lambda: threading.Semaphore(0))

    def translate(self, text: str, edge: DirectedEdge, context: tuple[str, ...] = ()) -> str:
        self.entered.release()
        assert self.gate.wait(5), "gate never released"
        return super().translate(text, edge, context)

    def wait_entered(self) -> None:
        assert self.entered.acquire(timeout=5), "translator never called"


@dataclass
class FakePacks:
    """A CAP-0171 pack catalog stand-in: a pack exists for the listed requirement subjects."""

    subjects: frozenset[str] = frozenset()

    def for_requirement(self, requirement):
        return object() if requirement.subject in self.subjects else None


@dataclass(frozen=True)
class Speakers:
    ready: bool
