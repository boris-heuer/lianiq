"""``PairedTranscriptModel``: the turn log rows for a ``QListView`` (paired-transcript §3.2).

Moved from ``listen_model.py`` (CAP-0170 §2.3) and generalised to ``TurnLog``.

Each row is stacked: ``HH:MM:SS · <source name>`` and the source text, then the translation
or the row state. A row whose text starts right to left is aligned right (the
``Qt.LayoutDirectionAuto`` rule per row); Unicode is never altered. The accessible text is
"``HH:MM:SS``, ``<source name>``: ``<source>``. ``<target name>``: ``<translation or state>``".
"""

from __future__ import annotations

import unicodedata

from PySide6.QtCore import QAbstractListModel, QModelIndex, QPersistentModelIndex, Qt

from lianiq.languages.registry import LanguageRegistry
from lianiq.pipeline_types import FailureReason
from lianiq.transcript.turns import Turn, TurnLog, TurnState
from lianiq.ui import strings

STATE_TEXT = {
    TurnState.RECOGNIZING: strings.LISTEN_RECOGNIZING,
    TurnState.TRANSLATING: strings.LISTEN_TRANSLATING,
    TurnState.NOT_UNDERSTOOD: strings.LISTEN_NOT_UNDERSTOOD,
    TurnState.SKIPPED: strings.LISTEN_SKIPPED,
    TurnState.NOT_FINISHED: strings.LISTEN_NOT_FINISHED,
}
REASON_TEXT = {
    FailureReason.MODEL: strings.LISTEN_REASON_MODEL,
    FailureReason.MEMORY: strings.LISTEN_REASON_MEMORY,
}
_RTL = frozenset({"R", "AL"})
_ROOT = QModelIndex()


def reason_text(reason: FailureReason | None) -> str:
    return REASON_TEXT.get(reason, strings.LISTEN_REASON_OTHER)


def right_to_left(text: str) -> bool:
    """The first strong character decides, as ``Qt.LayoutDirectionAuto`` does."""
    for character in text:
        kind = unicodedata.bidirectional(character)
        if kind in _RTL:
            return True
        if kind == "L":
            return False
    return False


class PairedTranscriptModel(QAbstractListModel):
    def __init__(self, transcript: TurnLog, registry: LanguageRegistry) -> None:
        super().__init__()
        self.transcript, self.registry = transcript, registry
        self._count = 0

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = _ROOT) -> int:
        return 0 if parent.isValid() else self._count

    def data(self, index, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= self._count:
            return None
        row = self.transcript.row(index.row())
        if role == Qt.ItemDataRole.DisplayRole:
            parts = (self.heading(row), row.source_text, self.outcome(row))
            return "\n".join(part for part in parts if part)
        if role == Qt.ItemDataRole.AccessibleTextRole:
            return self.accessible_text(row)
        if role == Qt.ItemDataRole.TextAlignmentRole:
            rtl = right_to_left(row.source_text or self.outcome(row))
            side = Qt.AlignmentFlag.AlignRight if rtl else Qt.AlignmentFlag.AlignLeft
            return int(side | Qt.AlignmentFlag.AlignVCenter)
        return None

    def heading(self, row: Turn) -> str:
        time = row.captured_at.strftime("%H:%M:%S")
        return f"{time} · {self.registry.display_name(row.source_language)}"

    @staticmethod
    def outcome(row: Turn) -> str:
        if row.state is TurnState.DONE and row.result is not None:
            return row.result.translated_text
        if row.state is TurnState.FAILED:
            return strings.LISTEN_SEGMENT_FAILED.format(reason=reason_text(row.reason))
        return STATE_TEXT.get(row.state, "")

    def accessible_text(self, row: Turn) -> str:
        time = row.captured_at.strftime("%H:%M:%S")
        source = self.registry.display_name(row.source_language)
        target = self.registry.display_name(row.target_language)
        return f"{time}, {source}: {row.source_text}. {target}: {self.outcome(row)}"

    def sync(self, changed: tuple[int, ...]) -> None:
        """Follow the log: one inserted row is inserted (no reset), others reset or update."""
        count = len(self.transcript)
        if count == self._count + 1 and len(changed) == 1:
            self.beginInsertRows(QModelIndex(), changed[0], changed[0])
            self._count = count
            self.endInsertRows()
            return
        if count != self._count:
            self.beginResetModel()
            self._count = count
            self.endResetModel()
            return
        for row in changed:
            if 0 <= row < count:
                cell = self.index(row)
                self.dataChanged.emit(cell, cell)
