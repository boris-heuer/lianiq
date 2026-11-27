"""``PairedTranscriptView``: the paired transcript of Conversation and Listen (spec §2.3, §3.2).

The list fills the height; under it *New turns below* with **Jump to latest** (hidden unless
needed), the per-turn row (**Copy original**, **Copy translation**, **Copy pair**, **Replay**,
**Stop playback**) and the transcript row (**Copy transcript**, **Export transcript**, the
clear action). **Replay** and **Stop playback** stay hidden until ``set_replay_visible``.
With large text the button rows wrap; every control has an accessible name equal to its
label. ``sync(changed)`` follows the log: a new row scrolls into view only when the list was
at its end; otherwise the position stays and *New turns below* shows.
"""

from __future__ import annotations

from PySide6.QtCore import QModelIndex, QTimer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from lianiq.languages.registry import LanguageRegistry
from lianiq.transcript.turns import Turn, TurnLog
from lianiq.ui import strings
from lianiq.ui.combo_fit import WrapWhenNarrow
from lianiq.ui.transcript.actions import TranscriptActions
from lianiq.ui.transcript.host import TranscriptHost
from lianiq.ui.transcript.model import PairedTranscriptModel
from lianiq.ui.transcript.turn_list import TranscriptList


def _button(text: str) -> QPushButton:
    button = QPushButton(text)
    button.setAccessibleName(text)
    return button


def _row(layout: QVBoxLayout, host: QWidget, widgets, tail, stretch_first=False) -> QHBoxLayout:
    row, second = QHBoxLayout(), QHBoxLayout()
    if stretch_first:
        row.addStretch(1)
        second.addStretch(1)
    for widget in widgets:
        row.addWidget(widget)
    if not stretch_first:
        row.addStretch(1)
        second.addStretch(1)
    layout.addLayout(row)
    layout.addLayout(second)
    host._wraps.append(WrapWhenNarrow(host, row, second, tail))
    return row


class PairedTranscriptView(TranscriptActions, QWidget):
    def __init__(
        self,
        log: TurnLog,
        registry: LanguageRegistry,
        clear_label: str,
        host: TranscriptHost,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.log, self.registry, self.host = log, registry, host
        self._replay_visible = False
        self._wraps: list[WrapWhenNarrow] = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        self.placeholder = QLabel()
        self.placeholder.setObjectName("transcriptEmpty")
        self.placeholder.setWordWrap(True)
        self.list = TranscriptList()
        self.model = PairedTranscriptModel(log, registry)
        self.list.setModel(self.model)
        layout.addWidget(self.placeholder)
        layout.addWidget(self.list, 1)

        jump = QHBoxLayout()
        self.new_below_label = QLabel(strings.TRANSCRIPT_NEW_BELOW)
        self.new_below_label.setObjectName("transcriptNewBelow")
        self.jump_button = _button(strings.TRANSCRIPT_JUMP)
        jump.addWidget(self.new_below_label)
        jump.addWidget(self.jump_button)
        jump.addStretch(1)
        layout.addLayout(jump)

        self.copy_original_button = _button(strings.TRANSCRIPT_COPY_ORIGINAL)
        self.copy_translation_button = _button(strings.TRANSCRIPT_COPY_TRANSLATION)
        self.copy_pair_button = _button(strings.TRANSCRIPT_COPY_PAIR)
        self.replay_button = _button(strings.TRANSCRIPT_REPLAY)
        self.stop_playback_button = _button(strings.TRANSCRIPT_STOP_PLAYBACK)
        turn_row = (
            self.copy_original_button,
            self.copy_translation_button,
            self.copy_pair_button,
            self.replay_button,
            self.stop_playback_button,
        )
        _row(layout, self, turn_row, list(turn_row[2:]))
        self.copy_all_button = _button(strings.TRANSCRIPT_COPY_ALL)
        self.export_button = _button(strings.TRANSCRIPT_EXPORT_ALL)
        self.clear_button = _button(clear_label)
        transcript_row = (self.copy_all_button, self.export_button, self.clear_button)
        _row(layout, self, transcript_row, [self.clear_button], stretch_first=True)
        self.connect_actions()
        self.set_replay_visible(False)
        self._show_new_below(False)
        self.refresh()

    # Follow.

    def at_end(self) -> bool:
        bar = self.list.verticalScrollBar()
        return bar.value() >= bar.maximum() - 2

    def _show_new_below(self, visible: bool) -> None:
        self.new_below_label.setVisible(visible)
        self.jump_button.setVisible(visible)

    def jump_to_latest(self) -> None:
        self.list.scrollToBottom()
        self._show_new_below(False)

    def _scrolled(self, _value: int) -> None:
        if self.at_end():
            self._show_new_below(False)

    def sync(self, changed: tuple[int | None, ...] = ()) -> None:
        """Refresh after a log change; ``changed`` names the changed row indexes."""
        changed = tuple(row for row in changed if row is not None)
        before = self.model.rowCount()
        following = self.at_end()
        self.model.sync(changed)
        count = self.model.rowCount()
        if count > before:
            if following:
                QTimer.singleShot(0, self.list.scrollToBottom)
            else:
                self._show_new_below(True)
        elif count == 0:
            self._show_new_below(False)
        self.refresh()

    def set_placeholder(self, text: str) -> None:
        """The empty-state line, shown while the list has no row."""
        self.placeholder.setText(text)
        self.placeholder.setVisible(bool(text) and not self.log.rows)

    # State.

    def current_turn(self) -> Turn | None:
        selection = self.list.selectionModel()
        indexes = selection.selectedIndexes() if selection is not None else []
        rows = self.log.rows
        if len(indexes) == 1 and 0 <= indexes[0].row() < len(rows):
            return rows[indexes[0].row()]
        return None

    def set_replay_visible(self, visible: bool) -> None:
        """WI-03 shows **Replay** and **Stop playback**."""
        self._replay_visible = visible
        self.replay_button.setVisible(visible)
        self.stop_playback_button.setVisible(visible)
        self.refresh()

    def refresh(self) -> None:
        """Enablement per spec §2.3 and §2.2.2."""
        turn = self.current_turn()
        translated = turn is not None and turn.translated
        self.copy_original_button.setEnabled(turn is not None and bool(turn.source_text))
        self.copy_translation_button.setEnabled(translated)
        self.copy_pair_button.setEnabled(translated)
        playing = self.host.playing()
        block = self.host.replay_block(turn) if translated else None
        self.replay_button.setEnabled(translated and block is None and not playing)
        self.replay_button.setToolTip(block or "")
        self.stop_playback_button.setEnabled(playing)
        rows = self.log.rows
        done = any(row.translated for row in rows)
        self.copy_all_button.setEnabled(done)
        self.export_button.setEnabled(done)
        self.clear_button.setEnabled(bool(rows))
        self.placeholder.setVisible(bool(self.placeholder.text()) and not rows)

    def select_row(self, row: int) -> None:
        """Select ``row`` without moving the view (the UI Automation path)."""
        index = self.model.index(row) if 0 <= row < self.model.rowCount() else QModelIndex()
        self.list.setCurrentIndex(index)
