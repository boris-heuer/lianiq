"""The voice row: one switch per pair language, its state and actions (CAP-0167 contract.md §7).

One instance sits under the Start row of Conversation and one mirrors it in Settings › Voice
output. Per language: the switch (visible text = the registry name, accessible name
"Speak {language}"), the state label ("{voice} · Ready", "Voice missing", "Voice files
invalid", "Not an output language in …"), **Open Language packs** (only while the voice is
missing or invalid) and **Voice options…** (only when the voice is ready and its engine offers
at least one control). Then **Replay** and **Stop playback**, shown while at least one voice
is ready, at the end of the first row. A long state wraps in its row; on a narrow page the
actions of a row move to a second line (``WrapWhenNarrow``), so nothing is cut.

The widget only shows state and emits requests; the workspaces write through
``VoicePreferences`` and refresh both instances.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from PySide6.QtCore import Signal
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from lianiq.config_voice import VoicePreferences
from lianiq.conversation.spoken_output import PlaybackState, VoiceState, VoiceStatus
from lianiq.languages.registry import LanguageId, LanguageRegistry
from lianiq.tts.voice_controls import VoiceControls
from lianiq.ui import strings
from lianiq.ui.combo_fit import WrapWhenNarrow


def state_text(
    status: VoiceStatus, registry: LanguageRegistry, statuses: Sequence[VoiceStatus]
) -> str:
    """The §2.3 state text of ``status``; ``statuses`` names the fixed target of the session."""
    if status.state is VoiceState.READY:
        return strings.VOICE_READY.format(voice=status.voice_name or "")
    if status.state is VoiceState.INVALID:
        return strings.VOICE_INVALID
    if status.state is VoiceState.MISSING:
        return strings.VOICE_STATE_MISSING
    others = [item.language for item in statuses if item.language != status.language]
    target = registry.display_name(others[0]) if others else ""
    direction = strings.ROUTING_FIXED.format(
        source=registry.display_name(status.language), target=target
    )
    return strings.VOICE_NOT_OUTPUT.format(direction=direction)


def offers_controls(controls: VoiceControls | None) -> bool:
    """Whether **Voice options…** has anything to show for these controls."""
    if controls is None:
        return False
    return controls.rate or controls.volume or (controls.speakers or 0) > 1


class _LanguageRow(QWidget):
    """One language's switch, state label and actions; the actions wrap to a second line."""

    def __init__(self, owner: VoiceOutputRows, language: LanguageId, name: str) -> None:
        super().__init__()
        self.language = language
        self.switch = QCheckBox(name)
        self.switch.setAccessibleName(strings.VOICE_SWITCH_NAME.format(language=name))
        self.switch.toggled.connect(lambda on: owner.switched.emit(str(language), on))
        self.state = QLabel()
        self.state.setWordWrap(True)  # a long state wraps inside its row, never cut
        policy = self.state.sizePolicy()
        policy.setHorizontalPolicy(QSizePolicy.Policy.Ignored)
        self.state.setSizePolicy(policy)
        self.state.setMinimumWidth(self.state.fontMetrics().horizontalAdvance("M" * 8))
        self.packs = QToolButton()
        self.packs.setText(strings.PACKS_OPEN)
        self.packs.setAccessibleName(strings.VOICE_PACKS_NAME.format(language=name))
        self.packs.clicked.connect(owner.packs_requested.emit)
        self.options = QToolButton()
        self.options.setText(strings.VOICE_OPTIONS)
        self.options.setAccessibleName(strings.VOICE_OPTIONS_NAME.format(language=name))
        self.options.clicked.connect(lambda: owner.options_requested.emit(str(language)))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        self.first, self.second = QHBoxLayout(), QHBoxLayout()
        for widget in (self.switch, self.state, self.packs, self.options):
            self.first.addWidget(widget)
        self.first.setStretch(1, 1)
        self.second.addStretch(1)
        layout.addLayout(self.first)
        layout.addLayout(self.second)
        self.wrap: WrapWhenNarrow | None = None

    def wrap_when_narrow(self, host: QWidget, extra: QWidget | None) -> None:
        """Move the actions (and ``extra``, the playback buttons) down when ``host`` is narrow."""
        if extra is not None:
            self.first.addWidget(extra)
        tail = [self.packs, self.options, *([extra] if extra is not None else [])]
        self.wrap = WrapWhenNarrow(host, self.first, self.second, tail)


class VoiceOutputRows(QWidget):
    switched = Signal(str, bool)  # language ID, on
    options_requested = Signal(str)  # language ID
    packs_requested = Signal()
    replay_requested = Signal()
    stop_playback_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAccessibleName(strings.VOICE_SECTION)
        self._rows_layout = QVBoxLayout(self)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(2)
        # **Replay** and **Stop playback** sit at the end of the first language row.
        self.playback = QWidget(self)
        playback = QHBoxLayout(self.playback)
        playback.setContentsMargins(0, 0, 0, 0)
        self.replay_button = QToolButton()
        self.replay_button.setText(strings.VOICE_REPLAY)
        self.replay_button.setAccessibleName(strings.VOICE_REPLAY)
        self.replay_button.clicked.connect(self.replay_requested.emit)
        self.stop_playback_button = QToolButton()
        self.stop_playback_button.setText(strings.VOICE_STOP_PLAYBACK)
        self.stop_playback_button.setAccessibleName(strings.VOICE_STOP_PLAYBACK)
        self.stop_playback_button.clicked.connect(self.stop_playback_requested.emit)
        playback.addWidget(self.replay_button)
        playback.addWidget(self.stop_playback_button)
        self._rows: dict[LanguageId, _LanguageRow] = {}
        self._statuses: tuple[VoiceStatus, ...] = ()
        self._switch_lock: str | None = None
        self._options_lock: tuple[frozenset[LanguageId], str | None] = (frozenset(), None)
        self.set_playback(PlaybackState.IDLE, False)
        self._show_playback(False)

    # Queries (tests and the workspaces) --------------------------------------------------

    def languages(self) -> tuple[LanguageId, ...]:
        return tuple(self._rows)

    def switch(self, language: LanguageId) -> QCheckBox:
        return self._rows[language].switch

    def state_label(self, language: LanguageId) -> QLabel:
        return self._rows[language].state

    def packs_button(self, language: LanguageId) -> QToolButton:
        return self._rows[language].packs

    def options_button(self, language: LanguageId) -> QToolButton:
        return self._rows[language].options

    # Updates -------------------------------------------------------------------------------

    def set_rows(
        self,
        statuses: Sequence[VoiceStatus],
        preferences: VoicePreferences,
        controls: Mapping[LanguageId, VoiceControls],
    ) -> None:
        """Show one row per status, in the given (pair) order."""
        registry = preferences.registry
        self._statuses = tuple(statuses)
        languages = tuple(status.language for status in self._statuses)
        if languages != tuple(self._rows):
            self._rebuild(languages, registry)
        for status in self._statuses:
            row = self._rows[status.language]
            ready = status.state is VoiceState.READY
            text = state_text(status, registry, self._statuses)
            name = registry.display_name(status.language)
            row.state.setText(text)
            row.state.setAccessibleName(strings.VOICE_STATE_NAME.format(language=name, state=text))
            row.switch.blockSignals(True)
            row.switch.setChecked(ready and preferences.get(status.language).enabled is not False)
            row.switch.blockSignals(False)
            row.packs.setVisible(status.state in (VoiceState.MISSING, VoiceState.INVALID))
            row.options.setVisible(ready and offers_controls(controls.get(status.language)))
        self._apply_locks()
        self._show_playback(any(status.state is VoiceState.READY for status in self._statuses))
        self._relayout()

    def _relayout(self) -> None:
        """New state texts change the width a row needs: re-check its wrap now."""
        for row in self._rows.values():
            if row.wrap is not None:
                host = row.wrap.parent()
                row.wrap.eventFilter(host, QResizeEvent(host.size(), host.size()))

    def set_switches_locked(self, reason: str | None) -> None:
        """While a Conversation runs the switches are locked (``LOCKED_TOOLTIP``)."""
        self._switch_lock = reason
        self._apply_locks()

    def set_options_locked(self, languages: frozenset[LanguageId], reason: str | None) -> None:
        """While Call Bridge or Meeting runs, **Voice options…** of its languages is locked."""
        self._options_lock = (frozenset(languages), reason)
        self._apply_locks()

    def set_playback(self, state: PlaybackState, can_replay: bool) -> None:
        """**Replay** iff something can be replayed and nothing plays; **Stop** while busy."""
        idle = state is PlaybackState.IDLE
        self.replay_button.setEnabled(can_replay and idle)
        self.replay_button.setToolTip("" if can_replay else strings.VOICE_REPLAY_EMPTY)
        self.stop_playback_button.setEnabled(not idle)

    # Internals -----------------------------------------------------------------------------

    def _rebuild(self, languages: tuple[LanguageId, ...], registry: LanguageRegistry) -> None:
        self.playback.setParent(self)  # kept: it moves to the new first row
        for row in self._rows.values():
            if row.wrap is not None:
                row.wrap.parent().removeEventFilter(row.wrap)
                row.wrap.deleteLater()
            self._rows_layout.removeWidget(row)
            row.deleteLater()
        self._rows = {}
        host = self.parentWidget() or self  # the page width decides, as for the action row
        for index, language in enumerate(languages):
            row = _LanguageRow(self, language, registry.display_name(language))
            row.wrap_when_narrow(host, self.playback if index == 0 else None)
            self._rows_layout.addWidget(row)
            self._rows[language] = row

    def _apply_locks(self) -> None:
        locked_languages, options_reason = self._options_lock
        for status in self._statuses:
            row = self._rows[status.language]
            ready = status.state is VoiceState.READY
            row.switch.setEnabled(ready and self._switch_lock is None)
            row.switch.setToolTip(self._switch_lock or "")
            options_locked = options_reason is not None and status.language in locked_languages
            row.options.setEnabled(not options_locked)
            row.options.setToolTip((options_reason or "") if options_locked else "")

    def _show_playback(self, visible: bool) -> None:
        self.replay_button.setVisible(visible)
        self.stop_playback_button.setVisible(visible)
