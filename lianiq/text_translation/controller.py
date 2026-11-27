"""Orchestrates the Text translation page (contract.md §8): draft, readiness and jobs.

Qt-free and GUI-thread only: worker callbacks arrive through the ``post`` of
``TranslationJobs``. The controller never writes the source editor; it renders a
``TextSnapshot`` after every change.

One job runs at a time: **Translate** after an edit while a job runs starts the new request
and the worker cancels the old one at its next segment; a late result of an older request or
revision is discarded (contract.md §3 rule 2). Failures post a notice through ``notify``
(``text-translation.failed`` or ``model_failed``), resolved by the next request.

**Play translation** / **Replay** play only a current result through ``TextPlayback`` (an
active session); an edit, language change, swap or a new shown result stops it (AC-30).
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
    PlayBlock,
    Speakers,
    TextReadiness,
    TranslateBlock,
    any_translation_ready,
    text_readiness,
)
from lianiq.text_translation.state import DraftState, ResultState, TextResult
from lianiq.ui import notice_catalog as catalog
from lianiq.ui import notice_catalog_text as notices
from lianiq.ui import strings_text as s
from lianiq.ui.notice_catalog_base import TEXT_TRANSLATION, source
from lianiq.ui.shell.session_owner import SessionBusy

if TYPE_CHECKING:
    from lianiq.languages.capabilities import CapabilityCatalog
    from lianiq.text_translation.playback import TextPlayback
    from lianiq.ui.notices import Notice

REASONS = {
    FailureReason.MODEL: s.TEXT_REASON_MODEL,
    FailureReason.MEMORY: s.TEXT_REASON_MEMORY,
    FailureReason.DEVICE: s.TEXT_REASON_DEVICE,
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
    replay: bool = False  # played == shown result_id
    status: str | None = None  # cancelled / failed text, never user text
    retry: bool = False  # Retry is offered after a cancel or failure
    no_pack: bool = False  # no translation pack for any edge: TEXT_NO_PACK_HINT


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
        playback: TextPlayback | None = None,
        open_audio: Callable[[], None] = lambda: None,
        open_packs: Callable[[], None] = lambda: None,
    ) -> None:
        self.registry = registry
        self._catalog, self._packs, self._speakers = catalog, packs, speakers
        self.jobs = jobs
        self._render = render
        self._notify, self._resolve = notify, resolve
        self.draft = DraftState(*languages)
        self.readiness = self._readiness()
        self.no_pack = not any_translation_ready(catalog())
        self.translating = False
        self._running_revision: int | None = None  # revision of the running request
        self.status: str | None = None
        self.retry_offered = False
        self._closed = False
        self.playback, self._open_audio, self._open_packs = playback, open_audio, open_packs
        if playback is not None:
            playback.on_change, playback.on_failed = self.render, self._playback_failed

    # Page events.

    def source_changed(self, text: str) -> None:
        """Typing, pasting or clearing: O(n), no translator call."""
        self.draft.edit(text)
        self._stop_stale()
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
        self.no_pack = not any_translation_ready(self._catalog())
        self._stop_stale()
        self.render()

    def can_play(self) -> bool:
        return (
            self.playback is not None
            and self.playback.state == "idle"
            and self.draft.current_result() is not None
            and self.readiness.play is PlayBlock.NONE
        )

    def play(self) -> None:
        """**Play translation** / **Replay**: the current result from the start."""
        if self._closed or not self.can_play():
            return
        self._resolve(notices.PLAYBACK_KEYS)
        try:
            self.playback.play(self.draft.current_result())
        except SessionBusy as busy:  # nothing synthesises (AC-27)
            self._notify(catalog.refused_start(TEXT_TRANSLATION, busy))

    def stop_playback(self) -> None:
        if self.playback is not None:
            self.playback.stop()

    def _stop_stale(self) -> None:
        """A playing result that is no longer the current one stops (AC-30)."""
        playing = None if self.playback is None else self.playback.playing
        current = self.draft.current_result()
        if playing is not None and (current is None or current.result_id != playing):
            self.playback.stop()

    def current_translation(self) -> str | None:
        """The text Copy translation may use: only a current result."""
        result = self.draft.current_result()
        return None if result is None else result.text

    def shutdown(self) -> None:
        self._closed = True
        self.stop_playback()
        self.jobs.shutdown()

    # Worker callbacks (on the GUI thread).

    def _done(self, result: TextResult) -> None:
        if self._closed:
            return
        self.draft.accept(result)
        self._stop_stale()
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

    def _playback_failed(self, reason: FailureReason) -> None:
        if not self._closed:
            self._notify(
                notices.playback_failed(
                    REASONS[reason], self.where(), self._open_audio, self._open_packs
                )
            )

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
        playback = self.playback
        current = self.draft.current_result()
        return TextSnapshot(
            check=check_source(self.draft.text),
            length=source_length(self.draft.text),
            readiness=self.readiness,
            translating=self.translating,
            result_text=None if result is None else result.text,
            result_state=self.draft.result_state,
            playback="idle" if playback is None else playback.state,
            replay=playback is not None
            and current is not None
            and playback.played == current.result_id,
            status=self.status,
            retry=self.retry_offered and not self.translating,
            no_pack=self.no_pack,
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
