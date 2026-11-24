"""The Call Bridge live text view (CAP-0166 spec §2.3, AC-13, AC-14).

A read-only list below the path boxes: each completed turn shows its direction (**You →
call** or **Call → you**), the original text and the translation, newest at the bottom. At
most ``MAX_TURNS`` turns are kept (the oldest is dropped); ``clear`` runs at every Start.
The text lives in memory only: nothing is written to disk, the settings or the logs, and the
view offers no copy or export action. Items are selectable for reading.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from lianiq.call_bridge.contracts import LaneId
from lianiq.domain import TranslationResult
from lianiq.ui import strings_call_bridge as s
from lianiq.ui.call_bridge_paths import PATH_NAMES

MAX_TURNS = 200


def turn_text(lane: LaneId, result: TranslationResult) -> str:
    """Direction, original and translation of one turn, one per line."""
    return f"{PATH_NAMES[lane]}\n{result.source_text}\n{result.translated_text}"


class CallBridgeTextView(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.title = QLabel(s.CB_TEXT_TITLE)
        layout.addWidget(self.title)
        self.empty_label = QLabel(s.CB_TEXT_EMPTY)
        self.empty_label.setAccessibleName(s.CB_TEXT_EMPTY)
        layout.addWidget(self.empty_label)
        self.list = QListWidget()
        self.list.setAccessibleName(s.CB_TEXT_TITLE)
        self.list.setWordWrap(True)
        self.list.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self.list.setMinimumHeight(120)
        self.title.setBuddy(self.list)
        layout.addWidget(self.list)
        self._show_empty()

    def turns(self) -> list[str]:
        return [self.list.item(row).text() for row in range(self.list.count())]

    def add_turn(self, lane: LaneId, result: TranslationResult) -> None:
        text = turn_text(lane, result)
        item = QListWidgetItem(text)
        item.setData(Qt.ItemDataRole.AccessibleTextRole, text.replace("\n", " · "))
        item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        self.list.addItem(item)
        while self.list.count() > MAX_TURNS:
            self.list.takeItem(0)  # the oldest turn is dropped
        self.list.scrollToBottom()
        self._show_empty()

    def clear(self) -> None:
        self.list.clear()
        self._show_empty()

    def _show_empty(self) -> None:
        empty = self.list.count() == 0
        self.empty_label.setVisible(empty)
        self.list.setVisible(not empty)
