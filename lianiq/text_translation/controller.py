"""Orchestrates the Text translation page (contract.md §8): draft, readiness and jobs.

Qt-free and GUI-thread only: worker callbacks arrive through the ``post`` of
``TranslationJobs``. The controller never writes the source editor; it renders a
``TextSnapshot`` after every change. Playback arrives with WI-04, so ``playback`` stays
``"idle"`` and ``replay`` ``False`` here.

One job runs at a time: **Translate** after an edit while a job runs starts the new request
and the worker cancels the old one at its next segment; a late result of an older request or
revision is discarded (contract.md §3 rule 2). Failures post a notice through ``notify``
(``text-translation.failed`` or ``model_failed``), resolved by the next request.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from lianiq.languages.registry import LanguageId, LanguageRegistry
from lianiq.text_translation.jobs import FailureReason, TranslationJobs
from lianiq.text_translation.limits import SourceCheck, check_source, source_length
from lianiq.text_translation.readiness import (
    PackLookup,
    Speakers,
    TextReadiness,
    TranslateBlock,
    text_readiness,
)
from lianiq.text_translation.state import DraftState, ResultState, TextResult
from lianiq.ui import notice_catalog_text as notices
from lianiq.ui import strings_text as s
from lianiq.ui.notice_catalog_base import TEXT_TRANSLATION, source

if TYPE_CHECKING:
    from lianiq.languages.capabilities import CapabilityCatalog
    from lianiq.ui.notices import Notice

REASONS = {
    FailureReason.MODEL: s.TEXT_REASON_MODEL,
    FailureReason.MEMORY: s.TEXT_REASON_MEMORY,
    FailureReason.OTHER: s.TEXT_REASON_OTHER,
}


@dataclass(frozen=True, slots=True)
class TextSnapshot:
    check: SourceCheck
    length: int
    readiness: TextReadiness
    translating: bool
    result_text: str | None
    result_state: ResultState
    playback: Literal["idle", "starting", "playing", "stopping"] = "idle"
    replay: bool = False  # played == shown result_id (WI-04)
    status: str | None = None  # cancelled / failed text, never user text
    retry: bool = False  # Retry is offered after a cancel or failure


class TextTranslationController:
    def __init__(
        self,
        registry: LanguageRegistry,
        catalog: Callable[[], CapabilityCatalog],
        packs: Callable[[], PackLookup | None],
        jobs: TranslationJobs,
        speakers: Callable[[], Speakers],
        render: Callable[[TextSnapshot], None],
        languages: tuple[LanguageId, LanguageId],
        notify: Callable[[Notice], None] = lambda _notice: None,
        resolve: Callable[[Sequence[str]], None] = lambda _keys: None,
    ) -> None:
        self.registry = registry
        self._catalog, self._packs, self._speakers = catalog, packs, speakers
        self.jobs = jobs
        self._render = render
        self._notify, self._resolve = notify, resolve
        self.draft = DraftState(*languages)
        self.readiness = self._readiness()
        self.translating = False
        self._running_revision: int | None = None  # revision of the running request
        self.status: str | None = None
        self.retry_offered = False
        self._closed = False

    # Page events.

    def source_changed(self, text: str) -> None:
        """Typing, pasting or clearing: O(n), no translator call."""
        self.draft.edit(text)
        self.render()

    def languages_changed(self, source: LanguageId, target: LanguageId) -> None:
        if (source, target) == (self.draft.source, self.draft.target):
            return
        self.draft.set_languages(source, target)
        self.refresh()

    def swap(self) -> None:
        self.draft.swap()
        self.refresh()

    @property
    def cancellable(self) -> bool:
        """A job runs for the shown revision: **Translate** reads **Cancel**."""
        return self.translating and self._running_revision == self.draft.revision

    def can_translate(self) -> bool:
        return (
            not self.cancellable
            and check_source(self.draft.text) is SourceCheck.OK
            and self.readiness.translate is TranslateBlock.NONE
        )

    def translate(self) -> None:
        """**Translate** / Ctrl+Enter: one request; a no-op unless allowed."""
        if self._closed or not self.can_translate():
            return
        request = self.draft.request()
        self.translating, self.status, self.retry_offered = True, None, False
        self._running_revision = request.revision
        self._resolve(notices.TEXT_FAILURE_KEYS)
        self.jobs.start(request, self._done, self._failed, self._cancelled)
        self.render()

    def cancel(self) -> None:
        if self.translating:
            self.jobs.cancel()

    def retry(self) -> None:
        self.translate()

    def refresh(self) -> None:
        """Readiness after a language, device or pack change; no restart needed."""
        self.readiness = self._readiness()
        self.render()

    def current_translation(self) -> str | None:
        """The text Copy translation may use: only a current result."""
        result = self.draft.current_result()
        return None if result is None else result.text

    def shutdown(self) -> None:
        self._closed = True
        self.jobs.shutdown()

    # Worker callbacks (on the GUI thread).

    def _done(self, result: TextResult) -> None:
        if self._closed:
            return
        self.draft.accept(result)
        self._finish(result.result_id, None)

    def _failed(self, request_id: int, reason: FailureReason) -> None:
        if self._closed or not self._finish(
            request_id, s.TEXT_FAILED.format(reason=REASONS[reason]), retry=True
        ):
            return
        build = (
            notices.model_failed if reason is FailureReason.MODEL else notices.translation_failed
        )
        self._notify(build(REASONS[reason], self.where(), self.retry))

    def _cancelled(self, request_id: int) -> None:
        if not self._closed:
            self._finish(request_id, s.TEXT_CANCELLED, retry=True)

    def _finish(self, request_id: int, status: str | None, retry: bool = False) -> bool:
        if request_id != self.draft.latest_request:
            return False  # a superseded job: its outcome is not shown
        self.translating, self.status, self.retry_offered = False, status, retry
        self._running_revision = None
        self.render()
        return True

    def where(self) -> str:
        """The notice source: "Text translation · German → Mandarin (Simplified)"."""
        name = self.registry.display_name
        return source(TEXT_TRANSLATION, f"{name(self.draft.source)} → {name(self.draft.target)}")

    # Rendering.

    def snapshot(self) -> TextSnapshot:
        result = self.draft.result
        return TextSnapshot(
            check=check_source(self.draft.text),
            length=source_length(self.draft.text),
            readiness=self.readiness,
            translating=self.translating,
            result_text=None if result is None else result.text,
            result_state=self.draft.result_state,
            status=self.status,
            retry=self.retry_offered and not self.translating,
        )

    def render(self) -> None:
        if not self._closed:
            self._render(self.snapshot())

    def _readiness(self) -> TextReadiness:
        return text_readiness(
            self.draft.source,
            self.draft.target,
            self._catalog(),
            self._packs(),
            self._speakers(),
        )
