"""The running meeting: status strip and running text view (CAP-0177 spec §2.3, WI-05).

``MeetingWorkspace`` base (file-size split). Stock widgets only; every one has an accessible
name. ``running_event`` takes each ``MeetingEvent`` on the GUI thread (the queued hand-off of
``MeetingWorkspace.meeting_event``):

* **Status strip**, per input: a level bar, the state (*Listening* / *Muted while speaking
  {language}* / *Device lost*) and the counter of other-language contributions; under it the
  *falling behind* notice while the turn queue is above its soft limit.
* **Running text view**: one line per accepted contribution, German (the local language)
  only, "Table" lines with the translation and "You" lines with the PO's recognised text,
  interleaved by speech end (``ended_at``). A table contribution shows *Translating…* until
  it is translated or withdrawn. The view follows the newest line unless the PO scrolled up
  (the Conversation ``ResultPanel`` follow-latest behaviour). Table-language text never
  reaches the page: no event carries it.

A placeholder has no ``ended_at`` yet; placeholders stay below every line, in arrival order,
and a line takes its place by speech end once it arrives. Lines stay visible after the meeting
until the next start; they live in memory only.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from datetime import datetime

from PySide6.QtWidgets import QGridLayout, QLabel, QProgressBar, QVBoxLayout, QWidget

from lianiq.meeting.contracts import CAPTURE_ROLES, MeetingRole
from lianiq.meeting.events import MeetingEvent, MeetingEventKind
from lianiq.ui import strings
from lianiq.ui.result_panel import ResultPanel

TABLE, USER = MeetingRole.TABLE_CAPTURE, MeetingRole.USER_CAPTURE
INPUT_NAMES = {TABLE: strings.MEETING_TABLE_MIC, USER: strings.MEETING_USER_MIC}
LINE_LABELS = {TABLE: strings.MEETING_LINE_TABLE, USER: strings.MEETING_LINE_YOU}
Kind = MeetingEventKind


@dataclass
class _Entry:
    role: MeetingRole
    text: str | None  # ``None``: still translating
    ended_at: datetime | None  # the line's speech end; ``None`` for a placeholder
    sequence: int

    def shown(self) -> str:
        return strings.MEETING_PENDING if self.text is None else self.text

    def order(self) -> tuple:
        if self.ended_at is None:  # placeholders after every line, in arrival order
            return (1, self.sequence)
        return (0, self.ended_at, self.sequence)


class MeetingRunning:
    """``MeetingWorkspace`` base: builds the strip and the view, shows the meeting events."""

    def build_running(self) -> QWidget:
        self.running_box = QWidget()
        self.running_box.setObjectName("meetingRunning")
        column = QVBoxLayout(self.running_box)
        column.setContentsMargins(0, 0, 0, 0)
        strip = QGridLayout()
        self.level_bars: dict[MeetingRole, QProgressBar] = {}
        self.input_states: dict[MeetingRole, QLabel] = {}
        self.ignored_labels: dict[MeetingRole, QLabel] = {}
        for row, (role, name) in enumerate(INPUT_NAMES.items()):
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setTextVisible(False)
            bar.setMaximumWidth(180)
            bar.setAccessibleName(name)
            self.level_bars[role] = bar
            self.input_states[role] = QLabel()
            self.ignored_labels[role] = QLabel()
            for column_index, widget in enumerate(
                (QLabel(name), bar, self.input_states[role], self.ignored_labels[role])
            ):
                strip.addWidget(widget, row, column_index)
        strip.setColumnStretch(3, 1)
        column.addLayout(strip)
        self.behind_label = QLabel(strings.MEETING_FALLING_BEHIND)
        self.behind_label.setObjectName("meetingBehind")
        column.addWidget(self.behind_label)
        self.running_view = ResultPanel(strings.MEETING_RUNNING_VIEW, "")
        column.addWidget(self.running_view, 1)
        self._entries: dict[object, _Entry] = {}
        self._sequence = itertools.count()
        self._lost_inputs: set[MeetingRole] = set()
        self.reset_running(running=False)
        return self.running_box

    def reset_running(self, running: bool) -> None:
        """At Start (``running``) clear the view and the counters; after Stop reset the strip."""
        if running:
            self._entries.clear()
            self._lost_inputs.clear()
            for label in self.ignored_labels.values():
                label.clear()
                label.hide()
            self._show_lines()
        for role in CAPTURE_ROLES:
            self.level_bars[role].setValue(0)
            self._set_state(role, "")
        self.behind_label.hide()
        self.running_view.text.setPlaceholderText(strings.MEETING_EMPTY if running else "")

    def show_level(self, role: MeetingRole, level: float) -> None:
        if (
            role in self.level_bars
            and role not in self._lost_inputs
            and self.controller is not None
        ):
            self.level_bars[role].setValue(round(max(0.0, min(level, 1.0)) * 100))

    def running_event(self, event: MeetingEvent) -> None:
        kind, role = event.kind, event.role
        if kind in (Kind.LISTENING, Kind.UNMUTED) and role not in self._lost_inputs:
            self._set_state(role, strings.MEETING_LISTENING)
        elif kind is Kind.MUTED and role not in self._lost_inputs:
            name = self.pipeline.registry.display_name(event.language)
            self._set_state(role, strings.MEETING_MUTED_WHILE_SPEAKING.format(language=name))
        elif kind is Kind.ENDPOINT_LOST:
            if role in CAPTURE_ROLES:
                self._lost_inputs.add(role)
                self.level_bars[role].setValue(0)
                self._set_state(role, strings.MEETING_DEVICE_LOST)
            self.show_endpoint_lost(role)
        elif kind is Kind.PENDING:
            entry = _Entry(role, None, None, next(self._sequence))
            self._entries.setdefault(event.contribution_id, entry)
            self._show_lines()
        elif kind is Kind.LINE:
            line = event.line
            self._entries[line.contribution_id] = _Entry(
                line.role, line.text, line.ended_at, next(self._sequence)
            )
            self._show_lines()
        elif kind is Kind.WITHDRAWN:
            if self._entries.pop(event.contribution_id, None) is not None:
                self._show_lines()
        elif kind is Kind.IGNORED:
            label = self.ignored_labels[role]
            label.setText(strings.MEETING_IGNORED_COUNT.format(count=event.count))
            label.show()
        elif kind in (Kind.FALLING_BEHIND, Kind.CAUGHT_UP):
            self.behind_label.setVisible(kind is Kind.FALLING_BEHIND)

    def _set_state(self, role: MeetingRole, text: str) -> None:
        label = self.input_states[role]
        label.setText(text)
        label.setAccessibleName(text or INPUT_NAMES[role])

    def _show_lines(self) -> None:
        lines = [
            f"{LINE_LABELS[entry.role]}: {entry.shown()}"
            for entry in sorted(self._entries.values(), key=_Entry.order)
        ]
        self.running_view.replace_text("\n".join(lines))
