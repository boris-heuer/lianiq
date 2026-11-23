"""Transcript follow, row notices, Copy and Export of the Listen page (CAP-0170 WI-04).

``ListenWorkspace`` base (file-size split). New rows scroll into view only when the list is
already at the bottom; otherwise the position stays and **Jump to latest** shows (spec
§2.2.2). A failed row posts ``listen.failed`` once; the first skipped row of a session posts
``listen.overload``. Copy and Export write transcript v2 of the ``DONE`` rows (contract.md §3);
a cancelled export writes nothing and shows nothing.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QFileDialog

from lianiq.languages.errors import LanguageContractError
from lianiq.listen.lifecycle import ListenSnapshot
from lianiq.listen.transcript import SegmentState
from lianiq.ui import notice_catalog as catalog
from lianiq.ui import notice_catalog_listen as listen_notices
from lianiq.ui import strings
from lianiq.ui.shell.workspaces import WorkspaceId
from lianiq.ui.workspaces.listen_model import reason_text

LISTEN = WorkspaceId.LISTEN
COPIED_MS = 1500


class ListenTranscriptActions:
    """Scrolling, row notices and the transcript actions; ``connect_actions`` wires them."""

    def connect_actions(self) -> None:
        self._noticed: set = set()  # turn IDs whose failure was posted
        self._overloaded: set[int] = set()  # sessions whose overload was posted
        self.copy_button.clicked.connect(self.copy_transcript)
        self.export_button.clicked.connect(self.export_transcript)
        self.jump_button.clicked.connect(self.jump_to_latest)
        bar = self.transcript_view.verticalScrollBar()
        bar.valueChanged.connect(lambda _value: self._at_bottom() and self._show_new_below(False))
        self._show_new_below(False)

    def _at_bottom(self) -> bool:
        bar = self.transcript_view.verticalScrollBar()
        return bar.value() >= bar.maximum() - 2

    def _show_new_below(self, visible: bool) -> None:
        self.new_below_label.setVisible(visible)
        self.jump_button.setVisible(visible)

    def jump_to_latest(self) -> None:
        self.transcript_view.scrollToBottom()
        self._show_new_below(False)

    def follow(self, snapshot: ListenSnapshot) -> None:
        """Apply ``snapshot``'s row changes: model, scroll, notices and the actions."""
        rows_before = self.model.rowCount()
        following = self._at_bottom()
        self.model.sync(snapshot.rows_changed)
        if self.model.rowCount() > rows_before:
            if following:
                QTimer.singleShot(0, self.transcript_view.scrollToBottom)
            else:
                self._show_new_below(True)
        self._post_row_notices(snapshot.rows_changed)
        self.copy_button.setEnabled(snapshot.can_export)
        self.export_button.setEnabled(snapshot.can_export)

    def _post_row_notices(self, changed: tuple[int, ...]) -> None:
        rows = self.controller.transcript.rows
        where = catalog.source(LISTEN)
        for index in changed:
            if not 0 <= index < len(rows):
                continue
            row = rows[index]
            if row.state is SegmentState.FAILED and row.turn_id not in self._noticed:
                self._noticed.add(row.turn_id)
                notice = listen_notices.segment_failed(
                    reason_text(row.reason), where, row.session_id
                )
                self.host.post_notice(notice)
            elif row.state is SegmentState.SKIPPED and row.session_id not in self._overloaded:
                self._overloaded.add(row.session_id)
                self.host.post_notice(listen_notices.overload(where, row.session_id))

    # Copy and Export.

    def transcript_text(self) -> str:
        """Transcript v2 of the ``DONE`` rows; the header names the current selection's pair."""
        try:
            pair = self.registry.pair(self.source, self.target)
        except LanguageContractError:
            row = self.controller.transcript.rows[0]
            pair = self.registry.pair(row.source_language, row.target_language)
        return self.controller.transcript.transcript_text(pair)

    def copy_transcript(self) -> None:
        if not self.copy_button.isEnabled():
            return
        QGuiApplication.clipboard().setText(self.transcript_text())
        self.copy_button.setText(strings.LISTEN_COPIED)
        QTimer.singleShot(COPIED_MS, lambda: self.copy_button.setText(strings.LISTEN_COPY))

    def export_transcript(self) -> None:
        if not self.export_button.isEnabled():
            return
        today = dt.datetime.now().astimezone().date().isoformat()
        default = str(Path.home() / f"listen-{today}.txt")
        path, _ = QFileDialog.getSaveFileName(
            self.host, strings.LISTEN_EXPORT, default, "Text (*.txt)"
        )
        self.export_button.setFocus()
        if not path:
            return  # cancelled: nothing written, no notice
        try:
            Path(path).write_text(self.transcript_text(), encoding="utf-8")
        except OSError as exc:
            diagnostics = self.host.diagnostics
            diagnostics.record("export", diagnostics.redact(f"Listen export failed: {exc}"))
            reason = self.host.diagnostics.redact(exc.strerror or str(exc))
            where = catalog.source(LISTEN, strings.TRANSCRIPT_EXPORT)
            self.host.post_notice(
                catalog.export_failed(LISTEN, reason, where, self.export_transcript)
            )
            return
        self.host.notices.resolve(catalog.export_failed_key(LISTEN))
        self.host.statusBar().showMessage(f"Transcript saved: {path}", 10_000)
