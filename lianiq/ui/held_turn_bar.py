"""The held-turn bar (CAP-0169 spec §2.3): resolve a turn whose spoken language is unclear.

A one-line bar of stock widgets: a warning icon, the title, the transcript excerpt (at most
120 characters, full text in the tooltip), the detected language, one **Translate as**
button per pair member, **Discard** and the counter "1 of n" when several turns are held.
Nothing is translated until the user clicks a button; ``Esc`` is deliberately not bound.

The excerpt yields the bar's width: it is elided to the space the other controls leave,
so the buttons always show their full labels (WI-08 DEV-01). It keeps a minimum width of the
first ``EXCERPT_MIN_CHARS`` characters, so even at the 850 px minimum window it shows them
(CAP-0168 RES-06, AC-11). For that the bar has two rows: the title, detected language and
counter above; the excerpt and the buttons below.

Keyboard focus never falls through to an unrelated control (WI-10 DEF-05): while a resolve
runs the bar itself keeps focus and the next held turn's first button receives it afterwards;
when the bar hides with focus inside it, focus goes to the first enabled focus return target.
"""

from __future__ import annotations

import itertools
from collections.abc import Sequence

from PySide6.QtCore import QEvent, QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from lianiq.conversation.routing import HeldTurn
from lianiq.languages.errors import UnknownLanguageError
from lianiq.languages.registry import LanguageId, LanguagePair, LanguageRegistry
from lianiq.ui import strings

EXCERPT_LENGTH = 120
# The excerpt never shrinks below this many characters (plus quote and ellipsis).
EXCERPT_MIN_CHARS = 20


def excerpt(text: str, limit: int = EXCERPT_LENGTH) -> str:
    """``text`` shortened to ``limit`` characters with a trailing ellipsis."""
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


class HeldTurnBar(QFrame):
    """Shows the oldest held turn; emits the user's explicit choice for it."""

    translate_requested = Signal(object, str)  # held turn, chosen source language ID
    discard_requested = Signal(object)  # held turn

    def __init__(self, registry: LanguageRegistry) -> None:
        super().__init__()
        self.registry = registry
        self.setObjectName("heldTurnBar")
        self.setAccessibleName(strings.HELD_TITLE)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self._turn: HeldTurn | None = None
        self._resolving = False
        rows = QVBoxLayout(self)
        rows.setContentsMargins(10, 6, 10, 6)
        rows.setSpacing(4)
        header = QHBoxLayout()
        layout = QHBoxLayout()
        rows.addLayout(header)
        rows.addLayout(layout)
        icon = QLabel()
        icon.setPixmap(
            self.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxWarning).pixmap(18, 18)
        )
        icon.setAccessibleName("Warning")
        self.title_label = QLabel(strings.HELD_TITLE)
        self.title_label.setObjectName("heldTitle")
        self.transcript_label = QLabel()
        self.transcript_label.setTextFormat(Qt.TextFormat.PlainText)
        # Ignored width: the excerpt takes only the space left over and is elided to it.
        self.transcript_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        self.transcript_label.installEventFilter(self)
        self._excerpt = ""
        self.detected_label = QLabel()
        self.counter_label = QLabel()
        header.addWidget(icon)
        header.addWidget(self.title_label)
        header.addStretch(1)
        header.addWidget(self.detected_label)
        header.addWidget(self.counter_label)
        layout.addWidget(self.transcript_label, 1)
        self._button_layout = QHBoxLayout()
        layout.addLayout(self._button_layout)
        self.translate_buttons: dict[LanguageId, QPushButton] = {}
        self.discard_button = QPushButton(strings.HELD_DISCARD)
        self.discard_button.setAccessibleName(strings.HELD_DISCARD)
        self.discard_button.clicked.connect(self._discard)
        layout.addWidget(self.discard_button)
        self._pair: LanguagePair | None = None
        self._focus_return: tuple[QWidget, ...] = ()
        self.hide()

    @property
    def turn(self) -> HeldTurn | None:
        """The held turn the bar shows, or ``None`` while hidden."""
        return self._turn

    @property
    def resolving(self) -> bool:
        return self._resolving

    @property
    def excerpt(self) -> str:
        """The quoted excerpt (at most 120 characters) before it is elided to the bar."""
        return self._excerpt

    def set_focus_return(self, *widgets: QWidget) -> None:
        """Where focus goes when the bar hides with focus inside it: the first enabled one."""
        self._focus_return = widgets

    def has_focus_within(self) -> bool:
        """Whether the bar or one of its buttons has the window's focus (also while inactive)."""
        focused = self.window().focusWidget()
        return focused is not None and (focused is self or self.isAncestorOf(focused))

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.transcript_label and event.type() == QEvent.Type.Resize:
            self._fit_excerpt()
        elif watched is self.transcript_label and event.type() in (
            QEvent.Type.FontChange,
            QEvent.Type.StyleChange,
        ):
            self._fit_minimum_width()
        return super().eventFilter(watched, event)

    def set_held(self, turns: Sequence[HeldTurn], pair: LanguagePair | None) -> None:
        """Show the oldest of ``turns`` with one button per member of ``pair``; hide if none."""
        if not turns or pair is None:
            self.clear()
            return
        self._set_pair(pair)
        turn = turns[0]
        self._turn = turn
        text = turn.transcript.text
        self._excerpt = f"“{excerpt(text)}”"
        self._fit_minimum_width()
        self._fit_excerpt()
        self.transcript_label.setToolTip(text)
        self.transcript_label.setAccessibleName(text)
        detected = self._detected_name(turn)
        self.detected_label.setText(
            strings.HELD_DETECTED.format(language=detected) if detected else ""
        )
        self.detected_label.setVisible(bool(detected))
        self.counter_label.setText(strings.HELD_COUNTER.format(index=1, count=len(turns)))
        self.counter_label.setVisible(len(turns) > 1)
        self._apply_enabled()
        self.show()
        if self.window().focusWidget() is self and not self._resolving:
            # Focus was parked on the bar during a resolve; continue with the next turn.
            next(iter(self.translate_buttons.values()), self.discard_button).setFocus(
                Qt.FocusReason.OtherFocusReason
            )

    def set_resolving(self, resolving: bool) -> None:
        """Disable the buttons while the chosen re-recognition runs."""
        if resolving and self.has_focus_within():
            # Disabling the focused button would move focus along the chain to an unrelated
            # control; the bar (named after its title) keeps it until the resolve reports back.
            self.setFocus(Qt.FocusReason.OtherFocusReason)
        self._resolving = resolving
        self._apply_enabled()

    def clear(self) -> None:
        if self.has_focus_within():
            chosen = self._return_focus()
            if chosen is not None:
                # A stop clears the bar before it disables **Stop** and enables **Start**;
                # once that settles, a target that became disabled hands focus on.
                QTimer.singleShot(0, self, lambda: chosen.isEnabled() or self._return_focus())
        self._turn = None
        self.hide()

    def _return_focus(self) -> QWidget | None:
        for widget in self._focus_return:
            if widget.isEnabled() and widget.isVisible():
                widget.setFocus(Qt.FocusReason.OtherFocusReason)
                return widget
        return None

    def _fit_minimum_width(self) -> None:
        """Room for the opening quote, ``EXCERPT_MIN_CHARS`` characters and the ellipsis."""
        label = self.transcript_label
        label.ensurePolished()
        shortest = self._excerpt[: EXCERPT_MIN_CHARS + 1] + "…"
        margins = label.contentsMargins()
        width = label.fontMetrics().horizontalAdvance(shortest) + margins.left() + margins.right()
        label.setMinimumWidth(width + 2 * label.margin() + 4 if self._excerpt else 0)

    def _fit_excerpt(self) -> None:
        label = self.transcript_label
        width = label.contentsRect().width()
        metrics = label.fontMetrics()
        label.setText(metrics.elidedText(self._excerpt, Qt.TextElideMode.ElideRight, width))

    def _set_pair(self, pair: LanguagePair) -> None:
        if pair == self._pair:
            return
        for button in self.translate_buttons.values():
            self._button_layout.removeWidget(button)
            button.deleteLater()
        self.translate_buttons = {}
        for language in pair.members:
            text = strings.HELD_TRANSLATE_AS.format(language=self.registry.display_name(language))
            button = QPushButton(text)
            button.setAccessibleName(text)
            button.clicked.connect(lambda _checked=False, chosen=language: self._translate(chosen))
            self._button_layout.addWidget(button)
            self.translate_buttons[language] = button
        self._pair = pair
        # Tab order: the Translate buttons in pair order, then Discard.
        buttons = [*self.translate_buttons.values(), self.discard_button]
        for first, second in itertools.pairwise(buttons):
            QFrame.setTabOrder(first, second)

    def _detected_name(self, turn: HeldTurn) -> str:
        language = turn.transcript.language
        if language is not None:
            try:
                return self.registry.display_name(language)
            except UnknownLanguageError:
                pass
        return turn.transcript.engine_language_code

    def _apply_enabled(self) -> None:
        enabled = self._turn is not None and not self._resolving
        for button in (*self.translate_buttons.values(), self.discard_button):
            button.setEnabled(enabled)

    def _translate(self, language: LanguageId) -> None:
        if self._turn is not None and not self._resolving:
            self.translate_requested.emit(self._turn, language)

    def _discard(self) -> None:
        if self._turn is not None and not self._resolving:
            self.discard_requested.emit(self._turn)
