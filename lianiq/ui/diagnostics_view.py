"""Settings › Diagnostics: the notice history with **Copy** and **Export…** (CAP-0168 §2.2.6).

The history shows ``DiagnosticsLog.export_text()``, the same redacted text **Copy** puts on
the clipboard and **Export…** writes; nothing leaves the app otherwise and no network is
used (contract §5). **Export…** opens a file dialog: a cancel or a write error keeps the
log and shows a notice, and only a written file shows "saved". The failure reason is
redacted too. Focus returns to the invoking button after the dialog (AC-28).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from lianiq.ui import notice_catalog as catalog
from lianiq.ui import strings
from lianiq.ui.shell.workspaces import WorkspaceId

if TYPE_CHECKING:
    from lianiq.ui.main_window import MainWindow

SETTINGS = WorkspaceId.SETTINGS


class DiagnosticsView(QGroupBox):
    def __init__(self, host: MainWindow) -> None:
        super().__init__(strings.DIAG_HISTORY)
        self.host = host
        self.setObjectName("diagnosticsHistory")
        layout = QVBoxLayout(self)
        self.history_text = QPlainTextEdit()
        self.history_text.setObjectName("diagnosticsText")
        self.history_text.setReadOnly(True)
        self.history_text.setAccessibleName(strings.DIAG_HISTORY)
        self.history_text.setPlaceholderText(strings.DIAG_EMPTY)
        self.history_text.setMinimumHeight(96)
        layout.addWidget(self.history_text, 1)
        buttons = QHBoxLayout()
        self.copy_button = QPushButton(strings.DIAG_COPY)
        self.copy_button.clicked.connect(self.copy)
        self.export_button = QPushButton(strings.DIAG_EXPORT)
        self.export_button.clicked.connect(self.export)
        buttons.addWidget(self.copy_button)
        buttons.addWidget(self.export_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        self.refresh()

    def refresh(self) -> None:
        """Show the current redacted log (or ``DIAG_EMPTY``)."""
        text = self.host.diagnostics.export_text()
        if self.history_text.toPlainText() != text:
            self.history_text.setPlainText(text)
            bar = self.history_text.verticalScrollBar()
            bar.setValue(bar.maximum())

    @Slot()
    def copy(self) -> None:
        QApplication.clipboard().setText(self.host.diagnostics.export_text())
        self._result(strings.DIAG_COPIED)

    @Slot()
    def export(self) -> None:
        default = str(Path.home() / strings.DIAG_EXPORT_NAME)
        path, _ = QFileDialog.getSaveFileName(
            self.host, strings.DIAG_EXPORT_TITLE, default, strings.DIAG_EXPORT_FILTER
        )
        self.export_button.setFocus(Qt.FocusReason.OtherFocusReason)
        if not path:
            self._result(strings.DIAG_EXPORT_CANCELLED)
            return
        text = self.host.diagnostics.export_text()
        try:
            Path(path).write_text(text, encoding="utf-8")
        except OSError as exc:
            self.host.diagnostics.record("export", f"Diagnostics export to {path} failed: {exc}")
            reason = self.host.diagnostics.redact(exc.strerror or str(exc))
            self.host.notices.resolve(catalog.export_result_key(SETTINGS))
            self.host.post_notice(
                catalog.export_failed(SETTINGS, reason, catalog.source(SETTINGS), self.export)
            )
            return
        self.host.notices.resolve(catalog.export_failed_key(SETTINGS))
        self._result(strings.DIAG_EXPORT_SAVED.format(name=Path(path).name))

    def _result(self, title: str) -> None:
        self.host.post_notice(catalog.export_result(SETTINGS, title, catalog.source(SETTINGS)))
