"""The Listen page as the ``TranscriptHost`` of its paired view, and its row notices.

``ListenWorkspace`` base (file-size split). Follow, copy, export and the clear confirmation
live in ``PairedTranscriptView`` (paired-transcript spec §3.4). A failed row posts
``listen.failed`` once; the first skipped row of a session posts ``listen.overload``.
**Clear transcript** stops a running session first (``ListenController.clear``). Replay stays
blocked here until WI-03; Listen never speaks on its own.
"""

from __future__ import annotations

from lianiq.languages.errors import LanguageContractError
from lianiq.languages.registry import LanguagePair
from lianiq.listen.lifecycle import ListenSnapshot
from lianiq.transcript.turns import Turn, TurnState
from lianiq.ui import notice_catalog as catalog
from lianiq.ui import notice_catalog_listen as listen_notices
from lianiq.ui.notices import Notice
from lianiq.ui.shell.workspaces import WorkspaceId
from lianiq.ui.transcript.model import reason_text

LISTEN = WorkspaceId.LISTEN


class ListenTranscriptActions:
    """``TranscriptHost`` members and the row notices; ``connect_actions`` resets them."""

    workspace = LISTEN
    export_prefix = "listen"

    def connect_actions(self) -> None:
        self._noticed: set = set()  # turn IDs whose failure was posted
        self._overloaded: set[int] = set()  # sessions whose overload was posted

    def follow(self, snapshot: ListenSnapshot) -> None:
        """Apply ``snapshot``'s row changes to the view, then post the row notices."""
        self.paired_view.sync(snapshot.rows_changed)
        self._post_row_notices(snapshot.rows_changed)

    def _post_row_notices(self, changed: tuple[int, ...]) -> None:
        rows = self.controller.transcript.rows
        where = catalog.source(LISTEN)
        for index in changed:
            if not 0 <= index < len(rows):
                continue
            row = rows[index]
            if row.state is TurnState.FAILED and row.turn_id not in self._noticed:
                self._noticed.add(row.turn_id)
                notice = listen_notices.segment_failed(
                    reason_text(row.reason), where, row.session_id
                )
                self.host.post_notice(notice)
            elif row.state is TurnState.SKIPPED and row.session_id not in self._overloaded:
                self._overloaded.add(row.session_id)
                self.host.post_notice(listen_notices.overload(where, row.session_id))

    # TranscriptHost.

    @property
    def main_window(self):
        return self.host

    def pair_for_export(self) -> LanguagePair:
        """The header names the current selection's pair, else the first row's."""
        try:
            return self.registry.pair(self.source, self.target)
        except LanguageContractError:
            row = self.controller.transcript.rows[0]
            return self.registry.pair(row.source_language, row.target_language)

    def replay_block(self, turn: Turn) -> str | None:
        return None  # the Replay button stays hidden until WI-03

    def replay(self, turn: Turn) -> None:
        """Listen gets per-turn Replay in WI-03."""

    def stop_playback(self) -> None:
        """Nothing plays from Listen before WI-03."""

    def playing(self) -> bool:
        return False

    def clear_session(self) -> None:
        self.controller.clear()

    def post_notice(self, notice: Notice) -> None:
        self.host.post_notice(notice)

    def transcript_text(self) -> str:
        """Transcript v2 of the ``DONE`` rows (what **Copy transcript** puts on the clipboard)."""
        return self.controller.transcript.transcript_text(self.pair_for_export())
