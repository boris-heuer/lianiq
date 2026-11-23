"""``ListenTranscriptModel``: the Listen transcript rows for a ``QListView`` (CAP-0170 §2.3).

Each row is stacked: ``HH:MM:SS · <source name>`` and the source text, then the translation
or the row state. A row whose text starts right to left is aligned right (the
``Qt.LayoutDirectionAuto`` rule per row); Unicode is never altered. The accessible text is
"``HH:MM:SS``, ``<source name>``: ``<source>``. ``<target name>``: ``<translation or state>``".
"""

from __future__ import annotations

import unicodedata

from PySide6.QtCore import QAbstractListModel, QModelIndex, QPersistentModelIndex, Qt

from lianiq.languages.registry import LanguageRegistry
from lianiq.listen.transcript import ListenTranscript, Segment, SegmentState
from lianiq.pipeline_types import FailureReason
from lianiq.ui import strings

STATE_TEXT = {
    SegmentState.RECOGNIZING: strings.LISTEN_RECOGNIZING,
    SegmentState.TRANSLATING: strings.LISTEN_TRANSLATING,
    SegmentState.NOT_UNDERSTOOD: strings.LISTEN_NOT_UNDERSTOOD,
    SegmentState.SKIPPED: strings.LISTEN_SKIPPED,
    SegmentState.NOT_FINISHED: strings.LISTEN_NOT_FINISHED,
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


class ListenTranscriptModel(QAbstractListModel):
    def __init__(self, transcript: ListenTranscript, registry: LanguageRegistry) -> None:
        super().__init__()
        self.transcript, self.registry = transcript, registry
        self._count = 0

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = _ROOT) -> int:
        return 0 if parent.isValid() else self._count

    def data(self, index, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= self._count:
            return None
        row = self.transcript.rows[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return "\n".join(part for part in (self.heading(row), row.source_text) if part) + (
                "\n" + self.outcome(row)
            )
        if role == Qt.ItemDataRole.AccessibleTextRole:
            return self.accessible_text(row)
        if role == Qt.ItemDataRole.TextAlignmentRole:
            rtl = right_to_left(row.source_text or self.outcome(row))
            side = Qt.AlignmentFlag.AlignRight if rtl else Qt.AlignmentFlag.AlignLeft
            return int(side | Qt.AlignmentFlag.AlignVCenter)
        return None

    def heading(self, row: Segment) -> str:
        time = row.captured_at.strftime("%H:%M:%S")
        return f"{time} · {self.registry.display_name(row.source_language)}"

    @staticmethod
    def outcome(row: Segment) -> str:
        if row.state is SegmentState.DONE and row.result is not None:
            return row.result.translated_text
        if row.state is SegmentState.FAILED:
            return strings.LISTEN_SEGMENT_FAILED.format(reason=reason_text(row.reason))
        return STATE_TEXT.get(row.state, "")

    def accessible_text(self, row: Segment) -> str:
        time = row.captured_at.strftime("%H:%M:%S")
        source = self.registry.display_name(row.source_language)
        target = self.registry.display_name(row.target_language)
        return f"{time}, {source}: {row.source_text}. {target}: {self.outcome(row)}"

    def sync(self, changed: tuple[int, ...]) -> None:
        """Follow the transcript: an inserted row is inserted, others are reset or updated."""
        count = len(self.transcript.rows)
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
