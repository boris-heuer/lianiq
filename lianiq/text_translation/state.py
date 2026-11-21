"""Draft revision, requests, results and the stale rule (contract.md §3).

One version identity, ``(revision, result_id)``, binds the shown text, Copy translation and
playback. Nothing here is persisted: closing the window drops the draft.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum

from lianiq.languages.capabilities import DirectedEdge
from lianiq.languages.registry import LanguageId
from lianiq.text_translation.limits import SourceCheck, check_source

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class TranslationRequest:
    request_id: int  # +1 per Translate or Retry
    revision: int  # draft revision at the click
    edge: DirectedEdge
    text: str  # in memory only

    def __repr__(self) -> str:  # never the user's text
        return (
            f"TranslationRequest(request_id={self.request_id}, revision={self.revision}, "
            f"edge={self.edge.key!r})"
        )


@dataclass(frozen=True, slots=True)
class TextResult:
    result_id: int  # the request_id of the job that made it
    revision: int
    edge: DirectedEdge
    text: str  # joined output (contract.md §4)
    segments: tuple[str, ...]  # translated sentences, used for playback

    def __repr__(self) -> str:  # never the user's text
        return (
            f"TextResult(result_id={self.result_id}, revision={self.revision}, "
            f"edge={self.edge.key!r}, segments={len(self.segments)})"
        )


class ResultState(StrEnum):
    NONE = "none"
    CURRENT = "current"
    STALE = "stale"


class DraftState:
    """The source draft, languages and shown result of the page. GUI thread only."""

    def __init__(self, source: LanguageId, target: LanguageId, text: str = "") -> None:
        self.revision = 0
        self.source = source
        self.target = target
        self.text = text
        self.result: TextResult | None = None
        self.latest_request: int | None = None
        self._next_request = 1

    def edit(self, text: str) -> None:
        """Typing, pasting or clearing: a new revision, and the shown result turns stale."""
        self.text = text
        self.revision += 1

    def set_languages(self, source: LanguageId, target: LanguageId) -> None:
        self.source = source
        self.target = target
        self.revision += 1

    def swap(self) -> None:
        """Exchange source and target; the draft text is unchanged."""
        self.set_languages(self.target, self.source)

    def request(self) -> TranslationRequest:
        """A new request for the current revision; ``ValueError`` unless the source is OK."""
        verdict = check_source(self.text)
        if verdict is not SourceCheck.OK:
            raise ValueError(f"Cannot translate: source is {verdict.value}")
        edge = DirectedEdge(self.source, self.target)
        request = TranslationRequest(self._next_request, self.revision, edge, self.text)
        self._next_request += 1
        self.latest_request = request.request_id
        return request

    def accept(self, result: TextResult) -> bool:
        """Show ``result`` only if it answers the latest request for the current revision."""
        if result.result_id != self.latest_request or result.revision != self.revision:
            LOGGER.info(
                "Discarded late text result: request=%d revision=%d",
                result.result_id,
                result.revision,
            )
            return False
        self.result = result
        return True

    @property
    def result_state(self) -> ResultState:
        if self.result is None:
            return ResultState.NONE
        if self.result.revision == self.revision:
            return ResultState.CURRENT
        return ResultState.STALE

    def current_result(self) -> TextResult | None:
        """The result Copy translation and Play may use: only a ``CURRENT`` one."""
        return self.result if self.result_state is ResultState.CURRENT else None
