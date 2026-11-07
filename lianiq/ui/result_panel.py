"""A titled, read-only result panel: *Original* or *Translation* (CAP-0168 WI-01, WI-02).

The panel names its text area after its visible title, so Windows UI Automation exposes the
Tab stop with a name (CAP-0169 WI-08 DEF-04, formerly set by ``ui/accessibility.py``).

Follow latest (CAP-0168 spec §2.3.3, RES-06 vs lianiq#69): the panel has a *follow* flag,
initially on. While it is on, every new result scrolls the panel to the end. Only the user's
own scrolling turns it off: a wheel turn, a scroll-bar press or drag, or PageUp/Up/Home/
Ctrl+Home in the panel that leaves the view above the end. Scrolling back to the end turns it
on again. Programmatic and UI Automation scrolling or selection (Narrator reading a panel)
never changes the flag, so results stay visible after a screen reader read the panel.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractSlider,
    QLabel,
    QPlainTextEdit,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

# User input that scrolls the view (spec §2.3.3); evaluated once Qt has handled it. The keys
# that move towards the end are included, so the user can also return to the end by keyboard.
_SCROLL_KEYS = {
    Qt.Key.Key_PageUp,
    Qt.Key.Key_PageDown,
    Qt.Key.Key_Up,
    Qt.Key.Key_Down,
    Qt.Key.Key_Home,
    Qt.Key.Key_End,
}
# A read-only text area ignores Home/End (and Ctrl+Home/Ctrl+End): they jump the view.
_JUMP_KEYS = {
    Qt.Key.Key_Home: QAbstractSlider.SliderAction.SliderToMinimum,
    Qt.Key.Key_End: QAbstractSlider.SliderAction.SliderToMaximum,
}
_JUMP_MODIFIERS = (Qt.KeyboardModifier.NoModifier, Qt.KeyboardModifier.ControlModifier)
_SCROLL_BAR_EVENTS = {
    QEvent.Type.MouseButtonPress,
    QEvent.Type.MouseButtonRelease,
    QEvent.Type.MouseMove,
}


class ResultPanel(QWidget):
    def __init__(self, title: str, placeholder: str) -> None:
        super().__init__()
        self.setObjectName("textPanel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        heading = QLabel(title)
        heading.setObjectName("panelTitle")
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setPlaceholderText(placeholder)
        self.text.setAccessibleName(title)
        self.text.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(heading)
        layout.addWidget(self.text)
        self.follow = True
        # The text area (keys), its viewport (wheel) and its scroll bar (press, drag, wheel).
        for target in (self.text, self.text.viewport(), self.text.verticalScrollBar()):
            target.installEventFilter(self)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if (
            watched is self.text
            and event.type() == QEvent.Type.KeyPress
            and event.key() in _JUMP_KEYS
            and event.modifiers() in _JUMP_MODIFIERS
        ):
            self.text.verticalScrollBar().triggerAction(_JUMP_KEYS[event.key()])
            self._follow_user_position()
            return True
        if self._is_user_scroll(watched, event):
            # After Qt applied the input, the flag follows where the user left the view.
            QTimer.singleShot(0, self, self._follow_user_position)
        return super().eventFilter(watched, event)

    def _is_user_scroll(self, watched: QObject, event: QEvent) -> bool:
        kind = event.type()
        if kind == QEvent.Type.Wheel:
            return True
        if watched is self.text.verticalScrollBar() and kind in _SCROLL_BAR_EVENTS:
            return kind != QEvent.Type.MouseMove or bool(event.buttons())
        return watched is self.text and kind == QEvent.Type.KeyPress and event.key() in _SCROLL_KEYS

    def at_end(self) -> bool:
        scroll_bar = self.text.verticalScrollBar()
        return scroll_bar.value() >= scroll_bar.maximum()

    def _follow_user_position(self) -> None:
        self.follow = self.at_end()

    def append_line(self, line: str) -> None:
        """Append ``line``; while *follow* is on, scroll the panel to it.

        ``appendPlainText`` follows new text only while the view is already at the bottom. A
        screen reader or UI Automation client that selects or scrolls to earlier text (Narrator
        reading a panel) leaves it elsewhere, and every later result would then be appended out
        of view (lianiq#69). That scrolling never clears *follow*, so the view still moves to
        the result; only the view moves, the caret and selection are kept. After the user
        scrolled up, *follow* is off and the view stays where the user left it.
        """
        scroll_bar = self.text.verticalScrollBar()
        kept = scroll_bar.value()
        self.text.appendPlainText(line)
        scroll_bar.setValue(scroll_bar.maximum() if self.follow else kept)
