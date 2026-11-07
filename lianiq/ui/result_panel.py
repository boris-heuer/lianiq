"""A titled, read-only result panel: *Original* or *Translation* (CAP-0168 WI-01).

The panel names its text area after its visible title, so Windows UI Automation exposes the
Tab stop with a name (CAP-0169 WI-08 DEF-04, formerly set by ``ui/accessibility.py``).
"""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QPlainTextEdit, QSizePolicy, QVBoxLayout, QWidget


class ResultPanel(QWidget):
    def __init__(self, title: str, placeholder: str) -> None:
        super().__init__()
        self.setObjectName("textPanel")
        layout = QVBoxLayout(self)
        heading = QLabel(title)
        heading.setObjectName("panelTitle")
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setPlaceholderText(placeholder)
        self.text.setAccessibleName(title)
        self.text.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(heading)
        layout.addWidget(self.text)

    def append_line(self, line: str) -> None:
        """Append ``line`` and always scroll the panel to it.

        ``appendPlainText`` follows new text only while the view is already at the bottom. A
        screen reader or UI Automation client that selects or scrolls to earlier text (Narrator
        reading a panel) leaves it elsewhere, and every later result would then be appended out
        of view (lianiq#69). Only the view moves; the caret and selection are kept.
        """
        self.text.appendPlainText(line)
        scroll_bar = self.text.verticalScrollBar()
        scroll_bar.setValue(scroll_bar.maximum())
