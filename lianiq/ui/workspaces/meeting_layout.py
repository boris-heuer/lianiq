"""The Meeting page: pair, devices, options and Start/End (CAP-0177 spec §2.1, §2.3).

``MeetingWorkspace`` base (file-size split). Stock widgets only, styled by ``theme.py``; every
control has an accessible name, and the Tab order follows the creation order: pair → devices
→ options → **Start meeting** / **End meeting** (spec §2.3 "Accessibility"). The content
scrolls; the Start/End row stays outside the scroll area (CAP-0168 spec §2.3.7). Labels that
name a language take the registry English name (``{language}``), never a literal.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from lianiq.meeting.contracts import MeetingRole, TableInputDuringOutput
from lianiq.ui import strings
from lianiq.ui.shell.scroll import workspace_scroll


def _combo(grid: QGridLayout, row: int, combos: dict, role: MeetingRole) -> QLabel:
    caption = QLabel()
    combo = QComboBox()
    combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    combo.setMinimumContentsLength(16)
    caption.setBuddy(combo)
    grid.addWidget(caption, row, 0)
    grid.addWidget(combo, row, 1)
    combos[role] = combo
    return caption


class MeetingLayout:
    """``MeetingWorkspace`` base: builds the page and names its language-bound labels."""

    def build_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("meetingPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        content = QWidget()
        column = QVBoxLayout(content)
        column.setContentsMargins(0, 0, 0, 0)
        column.addLayout(self._pair_row())
        column.addWidget(self._device_group())
        column.addWidget(self._options_group())
        self.availability_label = QLabel()
        self.availability_label.setObjectName("meetingAvailability")
        self.availability_label.setWordWrap(True)
        column.addWidget(self.availability_label)
        column.addStretch(1)
        layout.addWidget(workspace_scroll(content), 1)
        layout.addWidget(self._session_actions())
        self.name_languages()
        return page

    def _pair_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        caption = QLabel(strings.PAIR_LABEL)
        self.pair_combo = QComboBox()
        self.pair_combo.setAccessibleName(strings.PAIR_LABEL)
        caption.setBuddy(self.pair_combo)
        row.addWidget(caption)
        row.addWidget(self.pair_combo, 1)
        self.pair_combo.activated.connect(self._pair_activated)
        return row

    def _device_group(self) -> QWidget:
        self.combos: dict[MeetingRole, QComboBox] = {}
        self.role_captions: dict[MeetingRole, QLabel] = {}
        box = QWidget()
        column = QVBoxLayout(box)
        column.setContentsMargins(0, 0, 0, 0)
        table = QGroupBox(strings.MEETING_TABLE_GROUP)
        table_grid = QGridLayout(table)
        for row, role in enumerate((MeetingRole.TABLE_CAPTURE, MeetingRole.TABLE_RENDER)):
            self.role_captions[role] = _combo(table_grid, row, self.combos, role)
        table_grid.setColumnStretch(1, 1)
        column.addWidget(table)
        grid = QGridLayout()
        for row, role in enumerate((MeetingRole.USER_CAPTURE, MeetingRole.LOCAL_RENDER)):
            self.role_captions[role] = _combo(grid, row, self.combos, role)
        self.headset_checkbox = QCheckBox(strings.MEETING_LOCAL_IS_HEADSET)
        self.headset_checkbox.setAccessibleName(strings.MEETING_LOCAL_IS_HEADSET)
        self.headset_checkbox.setChecked(self.config.meeting.local_output_is_headset)
        self.headset_checkbox.toggled.connect(self._headset_toggled)
        grid.addWidget(self.headset_checkbox, 2, 1)
        self.refresh_button = QPushButton(strings.DEVICE_REFRESH)
        self.refresh_button.setAccessibleName(strings.DEVICE_REFRESH)
        self.refresh_button.clicked.connect(self.host.device_setup.refresh)
        grid.addWidget(self.refresh_button, 3, 0)
        grid.setColumnStretch(1, 1)
        column.addLayout(grid)
        for role, combo in self.combos.items():
            combo.activated.connect(lambda _index, role=role: self._combo_activated(role))
        return box

    def _options_group(self) -> QGroupBox:
        group = QGroupBox()
        column = QVBoxLayout(group)
        self.speak_local_checkbox = QCheckBox()
        self.speak_local_checkbox.toggled.connect(self._speak_local_toggled)
        column.addWidget(self.speak_local_checkbox)
        self.table_during_label = QLabel()
        column.addWidget(self.table_during_label)
        self.table_mode_group = QButtonGroup(group)
        self.table_mode_buttons: dict[TableInputDuringOutput, QRadioButton] = {}
        for mode, text in (
            (TableInputDuringOutput.MUTE, strings.MEETING_TABLE_MUTE),
            (TableInputDuringOutput.OPEN, strings.MEETING_TABLE_OPEN),
        ):
            button = QRadioButton(text)
            button.setAccessibleName(text)
            self.table_mode_group.addButton(button)
            self.table_mode_buttons[mode] = button
            column.addWidget(button)
            button.toggled.connect(lambda on, mode=mode: on and self._table_mode_chosen(mode))
        saved = TableInputDuringOutput(self.config.meeting.table_input_during_output)
        self.table_mode_buttons[saved].setChecked(True)
        return group

    def _session_actions(self) -> QWidget:
        self.session_actions = QWidget()
        row = QHBoxLayout(self.session_actions)
        row.setContentsMargins(0, 0, 0, 0)
        self.start_button = QPushButton(strings.MEETING_START)
        self.start_button.setObjectName("primaryButton")
        self.start_button.setAccessibleName(strings.MEETING_START)
        self.start_button.clicked.connect(self.start_meeting)
        self.end_button = QPushButton(strings.MEETING_END)
        self.end_button.setAccessibleName(strings.MEETING_END)
        self.end_button.setEnabled(False)
        self.end_button.clicked.connect(self.end_meeting)
        self.state_label = QLabel()
        self.state_label.setObjectName("meetingState")
        row.addWidget(self.start_button)
        row.addWidget(self.end_button)
        row.addWidget(self.state_label, 1)
        return self.session_actions

    def name_languages(self) -> None:
        """Set every label that names the local or the table language."""
        local, table = self.language_names()
        texts = {
            MeetingRole.TABLE_CAPTURE: strings.MEETING_TABLE_MIC,
            MeetingRole.TABLE_RENDER: strings.MEETING_TABLE_SPEAKER,
            MeetingRole.USER_CAPTURE: strings.MEETING_USER_MIC,
            MeetingRole.LOCAL_RENDER: strings.MEETING_LOCAL_OUTPUT.format(language=local),
        }
        for role, text in texts.items():
            self.role_captions[role].setText(text)
            self.combos[role].setAccessibleName(text)
        speak = strings.MEETING_SPEAK_LOCAL.format(language=local)
        self.speak_local_checkbox.setText(speak)
        self.speak_local_checkbox.setAccessibleName(speak)
        during = strings.MEETING_TABLE_DURING_OUTPUT.format(language=table)
        self.table_during_label.setText(during)
        for button in self.table_mode_buttons.values():
            button.setAccessibleDescription(during)

    def show_running(self, busy: bool) -> None:
        """Lock the setup while a meeting starts, runs or drains (``busy``)."""
        self.pair_combo.setEnabled(not busy and not self.host.session_locked())
        for combo in self.combos.values():
            combo.setEnabled(not busy)
        self.headset_checkbox.setEnabled(not busy)
        self.refresh_button.setEnabled(not busy)
        for button in self.table_mode_buttons.values():
            button.setEnabled(not busy)
            button.setToolTip(strings.MEETING_OPTIONS_LOCKED if busy else "")
        self.end_button.setEnabled(busy)
