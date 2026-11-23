"""Rendering of the Text translation page (CAP-0172 spec §2.2; file-size split).

``TextTranslationWorkspace`` base: turns a ``TextSnapshot`` into widget state. Each blocked
state that a pack can fix offers **Open Language packs** (CAP-0171 ``PACKS_OPEN``): the
readiness line for a missing translation pack, the empty result pane when no translation
pack is installed at all (``TEXT_NO_PACK_HINT``) and the play hint for a missing voice.
"""

from __future__ import annotations

from lianiq.languages.requirements import RequirementKind, describe
from lianiq.text_translation.controller import TextSnapshot
from lianiq.text_translation.limits import MAX_SOURCE_CODE_POINTS, SourceCheck
from lianiq.text_translation.readiness import PlayBlock, TranslateBlock
from lianiq.text_translation.state import ResultState
from lianiq.ui import strings


class TextTranslationRender:
    """Renders snapshots of ``self.controller`` into the widgets of the layout."""

    def render(self, snapshot: TextSnapshot) -> None:
        if not hasattr(self, "page"):
            return
        self.counter_label.setText(
            strings.TEXT_COUNTER.format(count=snapshot.length, limit=MAX_SOURCE_CODE_POINTS)
        )
        self.counter_label.setProperty("warning", snapshot.check is SourceCheck.TOO_LONG)
        self.readiness_label.setText(self._readiness_text(snapshot))
        self.readiness_label.setVisible(bool(self.readiness_label.text()))
        self.readiness_packs_button.setVisible(
            snapshot.check is not SourceCheck.TOO_LONG
            and snapshot.readiness.translate is TranslateBlock.PACK_MISSING
        )
        self.busy_indicator.setVisible(snapshot.translating)
        if self.controller.cancellable:
            self.translate_button.setText(strings.TEXT_CANCEL)
            self.translate_button.setEnabled(True)
        else:
            self.translate_button.setText(strings.TEXT_TRANSLATE)
            self.translate_button.setEnabled(self.controller.can_translate())
        self.translate_button.setAccessibleName(self.translate_button.text())
        self.retry_button.setVisible(snapshot.retry)
        playing = snapshot.playback != "idle"
        status = strings.TEXT_PLAYING if playing else snapshot.status or ""
        self.status_label.setText(strings.TEXT_TRANSLATING if snapshot.translating else status)
        self._render_play(snapshot, playing)
        result = self.controller.draft.result
        result_id = None if result is None else result.result_id
        if result_id != self._shown_result:
            self.result_edit.setPlainText(snapshot.result_text or "")
            self._shown_result = result_id
        empty = snapshot.no_pack and result is None
        self.result_edit.setPlaceholderText(
            strings.TEXT_NO_PACK_HINT if empty else strings.TEXT_RESULT_EMPTY
        )
        self.no_pack_button.setVisible(empty)
        stale = snapshot.result_state is ResultState.STALE
        self.stale_label.setVisible(stale)
        self.result_edit.setEnabled(not stale)  # dims the out-of-date text
        self.result_edit.setAccessibleDescription(
            " ".join(
                text
                for text in (strings.TEXT_STALE if stale else "", self.status_label.text())
                if text
            )
        )
        self.copy_translation_button.setEnabled(snapshot.result_state is ResultState.CURRENT)

    def _render_play(self, snapshot: TextSnapshot, playing: bool) -> None:
        """Play translation, then Replay after the first playback; Stop while playing."""
        label = strings.TEXT_REPLAY if snapshot.replay else strings.TEXT_PLAY
        self.play_button.setText(strings.TEXT_STOP if playing else label)
        self.play_button.setAccessibleName(self.play_button.text())
        self.play_button.setEnabled(playing or self.controller.can_play())
        block = snapshot.readiness.play
        hint = ""
        if block is PlayBlock.VOICE_MISSING:
            language = self.registry.display_name(self.controller.draft.target)
            hint = strings.TEXT_VOICE_MISSING.format(language=language)
        elif block is PlayBlock.SPEAKERS_MISSING:
            hint = strings.TEXT_SPEAKERS_MISSING
        self.play_hint.setText(hint)
        self.play_hint.setVisible(bool(hint))
        self.open_audio_button.setVisible(block is PlayBlock.SPEAKERS_MISSING)
        self.voice_packs_button.setVisible(block is PlayBlock.VOICE_MISSING)

    def _readiness_text(self, snapshot: TextSnapshot) -> str:
        if snapshot.check is SourceCheck.TOO_LONG:
            return strings.TEXT_TOO_LONG.format(count=snapshot.length, limit=MAX_SOURCE_CODE_POINTS)
        block = snapshot.readiness.translate
        draft = self.controller.draft
        if block is TranslateBlock.UNSUPPORTED:
            return strings.TEXT_UNSUPPORTED.format(
                source=self.registry.display_name(draft.source),
                target=self.registry.display_name(draft.target),
            )
        if block is TranslateBlock.PACK_MISSING:
            items = ", ".join(
                describe(item, self.registry)
                for item in snapshot.readiness.missing
                if item.kind is RequirementKind.TRANSLATION
            )
            return strings.MODE_UNAVAILABLE.format(items=items)
        if snapshot.check is SourceCheck.EMPTY:
            return strings.TEXT_EMPTY_REASON
        return ""
