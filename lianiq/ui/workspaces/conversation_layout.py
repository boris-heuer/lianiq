"""The controls of ``ConversationWorkspace`` (CAP-0168 file-size split)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from lianiq.ui import strings
from lianiq.ui.combo_fit import StackWhenNarrow, WhenNarrow, WrapWhenNarrow, fit_current_text
from lianiq.ui.held_turn_bar import HeldTurnBar
from lianiq.ui.result_panel import ResultPanel
from lianiq.ui.shell.scroll import workspace_scroll


class ConversationLayout:
    """``ConversationWorkspace`` base: its control row, held-turn bar and result panels."""

    def build(self, layout: QVBoxLayout) -> None:
        """Add the compact control row, the held-turn bar and the result panels to ``layout``."""
        controls = QGridLayout()
        controls.setHorizontalSpacing(10)
        self.pairs.build(controls)
        self.pair_combo, self.mode_combo = self.pairs.pair_combo, self.pairs.mode_combo

        self.tts_checkbox = QCheckBox(strings.VOICE_OUTPUT)
        self.tts_checkbox.setAccessibleName(strings.VOICE_OUTPUT)
        # Checked = the saved preference while spoken output is available (see
        # ``refresh_availability``); the output is bound to the session at Start.
        self.tts_checkbox.setChecked(self.config.voice_output)
        self.tts_checkbox.toggled.connect(self._toggle_tts)
        # Microphone and Speakers are in Settings › Audio devices (CAP-0168 WI-04).
        controls.setColumnStretch(2, 1)
        layout.addLayout(controls)

        # Long language names never widen the pinned row: the combos may shrink, but never
        # below their current entry (WI-05).
        self._combo_fits = [fit_current_text(c) for c in (self.pair_combo, self.mode_combo)]
        page = layout.parentWidget()
        self._field_row = StackWhenNarrow(page, controls, self.pair_combo, self.mode_combo)

        action_row = QHBoxLayout()
        self.start_button = QPushButton("▶  Start  (F8)")
        self.start_button.setObjectName("primaryButton")
        self.start_button.clicked.connect(self.start_listening)
        self.swap_button = QPushButton("⇄  Switch direction")
        self.swap_button.clicked.connect(self._swap_direction)
        self.export_button = QPushButton("Export transcript")
        self.export_button.clicked.connect(self.notices.export_transcript)
        action_row.addWidget(self.start_button)
        action_row.addWidget(self.swap_button)
        action_row.addSpacing(12)
        action_row.addWidget(self.tts_checkbox)
        action_row.addStretch()
        action_row.addWidget(self.export_button)
        layout.addLayout(action_row)
        # With large text, Voice output and Export move to a second line (never cut).
        second_row = QHBoxLayout()
        second_row.addStretch(1)
        layout.addLayout(second_row)
        tail = [self.tts_checkbox, self.export_button]
        self._action_row = WrapWhenNarrow(page, action_row, second_row, tail)

        # WI-05 (spec §2.3.7): the row with Start stays outside the scroll area; the held-turn
        # bar, the result panels and the level line scroll when the window is too small.
        content = QWidget()
        area = workspace_scroll(content)
        layout.addWidget(area, 1)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self.held_turn_bar = HeldTurnBar(self.pipeline.registry)
        self.held_turn_bar.translate_requested.connect(self._resolve_held)
        self.held_turn_bar.discard_requested.connect(self._discard_held)
        # While the session runs **Stop** is the next action; after a stop it is **Start**.
        self.held_turn_bar.set_focus_return(self.stop_button, self.start_button)
        layout.addWidget(self.held_turn_bar)
        bar = self.held_turn_bar
        self._held_fit = WhenNarrow(area.viewport(), bar.one_line_width, bar.set_stacked, bar)

        splitter = QSplitter(Qt.Horizontal)
        self.source_panel = ResultPanel("Original", strings.TRANSCRIPT_EMPTY)
        self.target_panel = ResultPanel("Translation", "The translation appears here …")
        splitter.addWidget(self.source_panel)
        splitter.addWidget(self.target_panel)
        splitter.setSizes([1, 1])
        layout.addWidget(splitter, 1)

        activity_row = QHBoxLayout()
        self.level_bar = QProgressBar()
        self.level_bar.setRange(0, 100)
        self.level_bar.setTextVisible(False)
        self.level_bar.setMaximumWidth(180)
        self.state_label = QLabel("Ready")
        self.latency_label = QLabel("Latency: –")
        activity_row.addWidget(QLabel("Microphone"))
        activity_row.addWidget(self.level_bar)
        activity_row.addWidget(self.state_label)
        activity_row.addStretch()
        activity_row.addWidget(self.latency_label)
        layout.addLayout(activity_row)

    @property
    def stop_button(self) -> QPushButton:
        """**Stop (F9)** of the session strip, which stops the active session."""
        return self.host.session_strip.stop_button

    @property
    def source_text(self):
        return self.source_panel.text

    @property
    def target_text(self):
        return self.target_panel.text

    def set_session_controls_enabled(self, enabled: bool) -> None:
        # Pair, routing and output are bound at Start (AC-13, PO decision Q2): changing
        # them needs Stop. While locked, the tooltip says why they are disabled.
        for control in (self.pair_combo, self.mode_combo, self.swap_button, self.tts_checkbox):
            control.setEnabled(enabled)
            control.setToolTip("" if enabled else strings.LOCKED_TOOLTIP)
        if enabled:
            self.refresh_availability()
        else:
            self.voice_output_changed.emit()

    def set_devices_enabled(self, enabled: bool) -> None:
        self.host.device_setup.set_enabled(enabled)
