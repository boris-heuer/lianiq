"""``TranscriptList``: the *Transcript* ``QListView`` of the paired view (spec §2.2.1, §2.3).

A programmatic or UI Automation selection never moves the view (``autoScroll`` off); keyboard
navigation still scrolls the current row into view. Ctrl+C asks for **Copy pair**; the Menu
key and Shift+F10 open the row context menu at the current row, a right click at the pointer.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QContextMenuEvent, QKeyEvent, QKeySequence
from PySide6.QtWidgets import QAbstractItemView, QListView, QStyledItemDelegate

from lianiq.ui import strings

SHIFT = Qt.KeyboardModifier.ShiftModifier


class TurnDelegate(QStyledItemDelegate):
    """Caches each row's wrapped size per width, so an insert into 2,000 rows lays out fast.

    A row's cache entry holds the ``Turn`` it was measured for; a changed row is a new
    ``Turn`` object (frozen) and is measured again.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._sizes: dict = {}

    def sizeHint(self, option, index):
        turn = index.model().transcript.row(index.row())
        width = option.rect.width()
        cached = self._sizes.get(turn.turn_id)
        if cached is not None and cached[0] is turn and cached[1] == width:
            return cached[2]
        size = super().sizeHint(option, index)
        self._sizes[turn.turn_id] = (turn, width, size)
        return size

    def forget(self) -> None:
        self._sizes.clear()


class TranscriptList(QListView):
    menu_requested = Signal(QPoint)  # global position
    copy_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("transcriptList")
        self.setAccessibleName(strings.TRANSCRIPT_LIST)
        self.setWordWrap(True)
        self.setUniformItemSizes(False)
        self.setSpacing(4)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setAutoScroll(False)
        self.delegate = TurnDelegate(self)
        self.setItemDelegate(self.delegate)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.matches(QKeySequence.StandardKey.Copy):
            event.accept()
            self.copy_requested.emit()
            return
        key, modifiers = event.key(), event.modifiers()
        if key == Qt.Key.Key_Menu or (key == Qt.Key.Key_F10 and modifiers == SHIFT):
            event.accept()
            self.menu_requested.emit(self.menu_point())
            return
        super().keyPressEvent(event)
        current = self.currentIndex()
        if current.isValid():
            self.scrollTo(current)

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        event.accept()
        if event.reason() == QContextMenuEvent.Reason.Keyboard:
            return  # the key press opened it already
        index = self.indexAt(event.pos())
        if index.isValid():
            self.setCurrentIndex(index)
        self.menu_requested.emit(event.globalPos())

    def menu_point(self) -> QPoint:
        """The current row's centre, or the list's centre without one."""
        current = self.currentIndex()
        rect = self.visualRect(current) if current.isValid() else self.viewport().rect()
        return self.viewport().mapToGlobal(rect.center())
