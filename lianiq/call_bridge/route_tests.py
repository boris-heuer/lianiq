"""Route-test results per Call Bridge path (CAP-0166 spec §3.1, AC-06).

A path is named by its lane: ``OUTBOUND`` is *You → call*, ``INBOUND`` is *Call → you*.
A result belongs to the path's fingerprint, ``(endpoint IDs of the path, pair, local
language)``; when ``update`` sees a new fingerprint that path returns to ``NOT_TESTED`` and
the other path keeps its result. A ``RouteTestState`` is never a lane activity, and nothing
here is persisted. Qt-free and not thread-safe: the UI owns the book.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType

from lianiq.call_bridge.contracts import EndpointRole, LaneId
from lianiq.languages.registry import LanguageId, LanguagePair


class RouteTestState(StrEnum):
    NOT_TESTED = "not_tested"
    PLAYING = "playing"
    AWAITING_ANSWER = "awaiting_answer"
    PASSED = "passed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PLAY_ERROR = "play_error"


PATH_ROLES = MappingProxyType(
    {
        LaneId.OUTBOUND: (EndpointRole.LOCAL_MICROPHONE, EndpointRole.CALL_MICROPHONE_RENDER),
        LaneId.INBOUND: (EndpointRole.CALL_SPEAKER_CAPTURE, EndpointRole.LOCAL_HEADPHONES),
    }
)

Fingerprint = tuple[tuple[str | None, ...], LanguagePair, LanguageId | None]


class RouteTestBook:
    def __init__(self) -> None:
        self._fingerprints: dict[LaneId, Fingerprint | None] = dict.fromkeys(LaneId)
        self._results = {path: (RouteTestState.NOT_TESTED, "") for path in LaneId}

    def update(
        self,
        assignments: Mapping[EndpointRole, str | None],
        pair: LanguagePair,
        local_language: LanguageId | None,
    ) -> frozenset[LaneId]:
        """Record the current setup; returns the paths whose result was reset."""
        reset: set[LaneId] = set()
        for path, roles in PATH_ROLES.items():
            fingerprint = (tuple(assignments.get(role) for role in roles), pair, local_language)
            previous = self._fingerprints[path]
            self._fingerprints[path] = fingerprint
            if previous is not None and previous != fingerprint:
                if self._results[path][0] is not RouteTestState.NOT_TESTED:
                    reset.add(path)
                self._results[path] = (RouteTestState.NOT_TESTED, "")
        return frozenset(reset)

    def set(self, path: LaneId, state: RouteTestState, detail: str = "") -> None:
        """The test row's new state; ``detail`` is the setting hint or the play error."""
        self._results[path] = (RouteTestState(state), detail)

    def state(self, path: LaneId) -> RouteTestState:
        return self._results[path][0]

    def detail(self, path: LaneId) -> str:
        return self._results[path][1]
