"""Combo boxes that never cut their current entry (CAP-0168 WI-05, AC-29/AC-32).

``QComboBox`` asks for the width of its longest entry, so one long (planned) language name
would widen the Conversation row beyond a small window. ``fit_current_text`` lets such a
combo shrink, but never below the width of the entry it shows; the shrinking falls on the
combos whose current entry is short. ``StackWhenNarrow`` stacks two such fields when even
their current entries do not fit side by side.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QSize
from PySide6.QtWidgets import QComboBox, QGridLayout, QStyle, QStyleOptionComboBox, QWidget

_REFIT_EVENTS = (QEvent.Type.FontChange, QEvent.Type.StyleChange, QEvent.Type.Polish)


def current_text_width(combo: QComboBox) -> int:
    """The width the combo needs to show its current entry in full (its own style)."""
    option = QStyleOptionComboBox()
    combo.initStyleOption(option)
    metrics = combo.fontMetrics()
    contents = QSize(metrics.horizontalAdvance(combo.currentText()), metrics.height())
    return (
        combo.style()
        .sizeFromContents(QStyle.ContentsType.CT_ComboBox, option, contents, combo)
        .width()
    )


class _CurrentTextFit(QObject):
    def __init__(self, combo: QComboBox) -> None:
        super().__init__(combo)
        self.combo = combo
        combo.installEventFilter(self)
        combo.currentIndexChanged.connect(self.fit)
        self.fit()

    def fit(self, *_args) -> None:
        self.combo.setMinimumWidth(current_text_width(self.combo))

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.combo and event.type() in _REFIT_EVENTS:
            self.fit()
        return False


def fit_current_text(combo: QComboBox) -> QObject:
    """Keep ``combo`` at least as wide as its current entry; it may shrink below its hint."""
    return _CurrentTextFit(combo)


class StackWhenNarrow(QObject):
    """Two captioned combos side by side in ``grid``; stacked when ``host`` is too narrow.

    With large text (Windows text scaling) the two current entries can be wider than the
    window; the second field then moves under the first instead of cutting either value.
    """

    def __init__(self, host: QWidget, grid: QGridLayout, first: QComboBox, second: QComboBox):
        super().__init__(host)
        self.grid, self.first, self.second = grid, first, second
        self.caption = grid.itemAtPosition(0, 1).widget()
        self.stacked = False
        host.installEventFilter(self)

    def needed(self) -> int:
        return self.first.minimumWidth() + self.second.minimumWidth() + self.grid.spacing()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.Resize:
            stacked = watched.width() < self.needed()
            if stacked != self.stacked:
                self.stacked = stacked
                row, column = (2, 0) if stacked else (0, 1)
                self.grid.addWidget(self.caption, row, column)
                self.grid.addWidget(self.second, row + 1, column)
        return False


class WrapWhenNarrow(QObject):
    """A row of buttons whose ``tail`` moves to ``second_row`` when ``host`` is too narrow."""

    def __init__(self, host: QWidget, first_row, second_row, tail: list[QWidget]) -> None:
        super().__init__(host)
        self.first_row, self.second_row = first_row, second_row
        self.positions = [(first_row.indexOf(widget), widget) for widget in tail]
        self.wrapped = False
        host.installEventFilter(self)

    def needed(self) -> int:
        """The width of the whole row on one line."""
        width = self.first_row.sizeHint().width()
        if self.wrapped:
            spacing = max(self.first_row.spacing(), 0)
            width += sum(widget.sizeHint().width() + spacing for _, widget in self.positions)
        return width

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.Resize:
            wrapped = watched.width() < self.needed()
            if wrapped != self.wrapped:
                self.wrapped = wrapped
                for index, widget in self.positions:
                    if wrapped:
                        self.first_row.removeWidget(widget)
                        self.second_row.addWidget(widget)
                    else:
                        self.second_row.removeWidget(widget)
                        self.first_row.insertWidget(index, widget)
        return False


class WhenNarrow(QObject):
    """``apply(True)`` while ``host`` is narrower than ``needed()``, else ``apply(False)``.

    Re-checked when ``host`` resizes and when ``watched`` shows or re-lays out (its content,
    and so ``needed()``, changed).
    """

    def __init__(self, host: QWidget, needed, apply, watched: QWidget) -> None:
        super().__init__(host)
        self.host, self.needed, self.apply, self.watched = host, needed, apply, watched
        self.narrow: bool | None = None
        host.installEventFilter(self)
        watched.installEventFilter(self)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        kinds = (QEvent.Type.Show, QEvent.Type.LayoutRequest)
        if (
            event.type() == QEvent.Type.Resize
            and watched is self.host
            or (watched is self.watched and event.type() in kinds)
        ):
            narrow = self.host.width() < self.needed()
            if narrow != self.narrow:
                self.narrow = narrow
                self.apply(narrow)
        return False
