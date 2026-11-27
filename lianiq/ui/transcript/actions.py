"""Copy, export, clear and the row context menu of ``PairedTranscriptView`` (spec §2.2, §2.3).

``PairedTranscriptView`` base (file-size split). Copy and export run on a click only. Export
writes transcript v2 (UTF-8); "Transcript saved: {path}" shows, and the exported turns count
as saved, only after a successful write. A cancelled export writes and shows nothing; a
failed one posts the workspace's ``export_failed`` notice with **Retry**. The clear action asks
first only while an unsaved translated turn exists; **Cancel** is the default and Escape.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from PySide6.QtCore import QPoint, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QFileDialog, QMenu, QMessageBox, QPushButton

from lianiq.transcript.turns import TurnPart, turn_text
from lianiq.ui import notice_catalog as catalog
from lianiq.ui import strings

COPIED_MS = 1500


class TranscriptActions:
    """Wired by ``connect_actions``; the view provides the widgets, ``log`` and ``host``."""

    def connect_actions(self) -> None:
        self.menu: QMenu | None = None
        self.copy_original_button.clicked.connect(lambda: self.copy_turn(TurnPart.ORIGINAL))
        self.copy_translation_button.clicked.connect(lambda: self.copy_turn(TurnPart.TRANSLATION))
        self.copy_pair_button.clicked.connect(lambda: self.copy_turn(TurnPart.PAIR))
        self.replay_button.clicked.connect(self.replay_current)
        self.stop_playback_button.clicked.connect(self.host.stop_playback)
        self.copy_all_button.clicked.connect(self.copy_transcript)
        self.export_button.clicked.connect(self.export_transcript)
        self.clear_button.clicked.connect(self.request_clear)
        self.jump_button.clicked.connect(self.jump_to_latest)
        self.list.verticalScrollBar().valueChanged.connect(self._scrolled)
        self.list.verticalScrollBar().rangeChanged.connect(self._keep_following)
        self.list.selectionModel().selectionChanged.connect(lambda *_: self.refresh())
        self.model.modelReset.connect(self.list.delegate.forget)
        self.model.modelReset.connect(self.refresh)
        self.list.copy_requested.connect(lambda: self.copy_turn(TurnPart.PAIR))
        self.list.menu_requested.connect(self.open_menu)

    # Per turn.

    def _part_button(self, part: TurnPart) -> QPushButton:
        return {
            TurnPart.ORIGINAL: self.copy_original_button,
            TurnPart.TRANSLATION: self.copy_translation_button,
            TurnPart.PAIR: self.copy_pair_button,
        }[part]

    def copy_turn(self, part: TurnPart) -> None:
        button = self._part_button(part)
        turn = self.current_turn()
        if turn is None or not button.isEnabled():
            return
        QGuiApplication.clipboard().setText(turn_text(turn, part, self.registry))
        self._flash(button, button.accessibleName())

    def replay_current(self) -> None:
        turn = self.current_turn()
        if turn is not None and self.replay_button.isEnabled():
            self.host.replay(turn)
            self.refresh()

    def _flash(self, button: QPushButton, label: str) -> None:
        """The button reads "Copied" for 1.5 s; its accessible name stays."""
        button.setText(strings.TRANSCRIPT_COPIED)
        QTimer.singleShot(COPIED_MS, lambda: button.setText(label))

    def build_menu(self) -> QMenu:
        menu = QMenu(self)
        menu.setAccessibleName(strings.TRANSCRIPT_LIST)
        entries = (
            (self.copy_original_button, lambda: self.copy_turn(TurnPart.ORIGINAL)),
            (self.copy_translation_button, lambda: self.copy_turn(TurnPart.TRANSLATION)),
            (self.copy_pair_button, lambda: self.copy_turn(TurnPart.PAIR)),
            (self.replay_button, self.replay_current),
        )
        for button, run in entries:
            action = menu.addAction(button.accessibleName())
            action.setEnabled(button.isEnabled())
            action.setVisible(button is not self.replay_button or self._replay_visible)
            action.triggered.connect(run)
        return menu

    def open_menu(self, point: QPoint) -> None:
        if self.current_turn() is None:
            return
        self.menu = self.build_menu()
        self.menu.popup(point)

    # The whole transcript.

    def copy_transcript(self) -> None:
        if not self.copy_all_button.isEnabled():
            return
        QGuiApplication.clipboard().setText(self.log.transcript_text(self.host.pair_for_export()))
        self._flash(self.copy_all_button, strings.TRANSCRIPT_COPY_ALL)

    def export_transcript(self) -> None:
        if not self.export_button.isEnabled():
            return
        window, workspace = self.host.main_window, self.host.workspace
        today = dt.datetime.now().astimezone().date().isoformat()
        default = str(Path.home() / f"{self.host.export_prefix}-{today}.txt")
        path, _ = QFileDialog.getSaveFileName(
            window, strings.TRANSCRIPT_EXPORT_ALL, default, "Text (*.txt)"
        )
        self.export_button.setFocus()
        if not path:
            return  # cancelled: nothing written, no notice
        exported = [result.turn_id for result in self.log.results()]
        text = self.log.transcript_text(self.host.pair_for_export())
        try:
            Path(path).write_text(text, encoding="utf-8")
        except OSError as exc:
            diagnostics = window.diagnostics
            diagnostics.record("export", diagnostics.redact(f"Transcript export failed: {exc}"))
            reason = diagnostics.redact(exc.strerror or str(exc))
            where = catalog.source(workspace, strings.TRANSCRIPT_EXPORT)
            self.host.post_notice(
                catalog.export_failed(workspace, reason, where, self.export_transcript)
            )
            return
        self.log.mark_exported(exported)
        window.notices.resolve(catalog.export_failed_key(workspace))
        window.statusBar().showMessage(strings.TRANSCRIPT_SAVED.format(path=path), 10_000)

    # Clear.

    def clear_box(self, count: int) -> QMessageBox:
        box = QMessageBox(self.host.main_window)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(strings.TRANSCRIPT_CLEAR_TITLE)
        box.setText(strings.TRANSCRIPT_CLEAR_TEXT.format(count=count))
        box.confirm_button = box.addButton(
            strings.TRANSCRIPT_CLEAR_CONFIRM, QMessageBox.ButtonRole.DestructiveRole
        )
        cancel = box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(cancel)
        box.setEscapeButton(cancel)
        return box

    def confirm_clear(self, count: int) -> bool:
        box = self.clear_box(count)
        box.exec()
        confirmed = box.clickedButton() is box.confirm_button
        box.deleteLater()
        return confirmed

    def request_clear(self) -> None:
        """The clear action (spec §2.2.1 step 6); a cancel changes nothing."""
        if not self.clear_button.isEnabled():
            return
        count = self.log.unsaved_count()
        if count and not self.confirm_clear(count):
            self.clear_button.setFocus()
            return
        self.host.clear_session()
        self.sync(())
        self._show_new_below(False)
        (self.clear_button if self.clear_button.isEnabled() else self.list).setFocus()
