"""The Conversation turns and the ``TranscriptHost`` of its paired view (paired-transcript §3.4).

``ConversationWorkspace`` base (file-size split). Completed turns go into ``turns``
(``TurnLog``, in memory only) at their capture time, with the owner generation the runner
bound when it emitted the result. A normal **Stop** does not finish the session in the log,
so queued turns that complete after it still appear. Only **New conversation** finishes it:
it ends a playback and stops a running or starting session first, then clears the log, so
a late result of that session never adds a row. Copy, export and the confirmation live in
``PairedTranscriptView``; per-turn **Replay** is ``ReplayHost`` (WI-03).
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Slot

from lianiq.domain import TranslationResult
from lianiq.languages.registry import LanguagePair
from lianiq.ui import strings
from lianiq.ui.notices import Notice
from lianiq.ui.shell.workspaces import WorkspaceId
from lianiq.ui.transcript.replay import ReplayHost


class ConversationTranscript(ReplayHost):
    """``TranscriptHost`` members, the result slot and the transcript forwards."""

    workspace = WorkspaceId.CONVERSATION
    export_prefix = "conversation"

    @Slot(object, int)
    def _show_result(self, result: TranslationResult, generation: int) -> None:
        name = self.pipeline.registry.display_name
        source, target = name(result.source_language), name(result.target_language)
        self.paired_view.sync((self.turns.add_result(result, generation),))
        direction = strings.ROUTING_FIXED.format(source=source, target=target)
        self.latency_label.setText(f"{direction} · Processing: {result.total_seconds:.2f} s")
        self.notices.record_result(result)

    @property
    def history(self) -> tuple[TranslationResult, ...]:
        """The completed turns in capture order."""
        return self.turns.results()

    def write_transcript(self, path: Path) -> None:
        """Write the completed turns as transcript v2 (UTF-8), ordered by capture time."""
        Path(path).write_text(self.turns.transcript_text(self.pair_for_export()), encoding="utf-8")

    # TranscriptHost.

    @property
    def main_window(self):
        return self.host

    def pair_for_export(self) -> LanguagePair:
        """The running session's pair, else the selected one, else the configured one."""
        session = self.session_controller.session
        pair = session.pair if session is not None else self.current_pair()
        if pair is None:
            pair = self.pipeline.registry.pair(*self.config.languages.pair)
        return pair

    def clear_session(self) -> None:
        """**New conversation**: end a playback, stop a running or starting session, clear."""
        self.stop_playback()
        if self.starting or self.capture.running:
            self.stop_listening()
        self.turns.finish_session(self._generation)  # also a session without a row yet
        self.turns.clear()

    def post_notice(self, notice: Notice) -> None:
        self.host.post_notice(notice)
