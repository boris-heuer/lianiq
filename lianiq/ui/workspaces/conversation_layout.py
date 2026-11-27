"""The controls of ``ConversationWorkspace`` (CAP-0168 file-size split).

The paired transcript view replaces the *Original*/*Translation* splitter (paired-transcript
spec §2.3): its list fills the scroll area, with **Copy transcript**, **Export transcript** and
**New conversation** under it.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from lianiq.ui import strings
from lianiq.ui.combo_fit import StackWhenNarrow, WhenNarrow, fit_current_text
from lianiq.ui.held_turn_bar import HeldTurnBar
from lianiq.ui.shell.scroll import workspace_scroll
from lianiq.ui.transcript.view import PairedTranscriptView
from lianiq.ui.voice_output_rows import VoiceOutputRows


class ConversationLayout:
    """``ConversationWorkspace`` base: its control row, held-turn bar and transcript view."""

    def build(self, layout: QVBoxLayout) -> None:
        """Add the compact control row, the held-turn bar and the transcript view to ``layout``."""
        controls = QGridLayout()
        controls.setHorizontalSpacing(10)
        self.pairs.build(controls)
        self.pair_combo, self.mode_combo = self.pairs.pair_combo, self.pairs.mode_combo

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
        action_row.addWidget(self.start_button)
        action_row.addWidget(self.swap_button)
        action_row.addStretch()
        layout.addLayout(action_row)
        # CAP-0167 WI-03: one voice switch per pair language under the Start row; the
        # spoken plan they select is bound at Start (``refresh_availability``).
        self.voice_rows = VoiceOutputRows(page)
        self.voice_rows.switched.connect(self._voice_switched)
        self.voice_rows.packs_requested.connect(self.open_language_packs)
        self.voice_rows.options_requested.connect(self.open_voice_options)
        self.voice_rows.replay_requested.connect(self.replay_spoken)
        self.voice_rows.stop_playback_requested.connect(self.stop_spoken)
        layout.addWidget(self.voice_rows)

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

        # The paired transcript (spec §3.4); ``conversation_availability`` sets its empty line.
        view = PairedTranscriptView(
            self.turns, self.pipeline.registry, strings.TRANSCRIPT_NEW_CONVERSATION, self
        )
        view.set_placeholder(strings.TRANSCRIPT_EMPTY)
        view.set_replay_visible(True)  # per-turn Replay / Stop playback (WI-03)
        layout.addWidget(view, 1)
        self.paired_view, self.transcript_view = view, view.list
        self.export_button, self.copy_button = view.export_button, view.copy_all_button
        self.clear_button = view.clear_button

        activity_row = QHBoxLayout()
        self.level_bar = QProgressBar()
        self.level_bar.setRange(0, 100)
        self.level_bar.setTextVisible(False)
        self.level_bar.setMaximumWidth(180)
        self.state_label = QLabel("Ready")
        self.latency_label = QLabel("Latency: –")
        caption = QLabel(strings.NOTICE_MICROPHONE)
        # The microphone chosen in Settings › Audio devices, as its combo names it (#137).
        self.microphone_label = QLabel()
        self.microphone_label.setAccessibleName(strings.NOTICE_MICROPHONE)
        self.microphone_label.setWordWrap(True)  # a long name wraps, never widens the row
        policy = self.microphone_label.sizePolicy()
        policy.setHorizontalPolicy(QSizePolicy.Policy.Ignored)  # no minimum width of its own
        self.microphone_label.setSizePolicy(policy)
        caption.setBuddy(self.microphone_label)
        activity_row.addWidget(caption)
        activity_row.addWidget(self.microphone_label, 1)
        activity_row.addWidget(self.level_bar)
        activity_row.addWidget(self.state_label)
        activity_row.addStretch()
        activity_row.addWidget(self.latency_label)
        layout.addLayout(activity_row)

    @property
    def stop_button(self) -> QPushButton:
        """**Stop (F9)** of the session strip, which stops the active session."""
        return self.host.session_strip.stop_button

    def set_session_controls_enabled(self, enabled: bool) -> None:
        # Pair, routing and the voice switches are bound at Start (AC-13, PO decision Q2):
        # changing them needs Stop. While locked, the tooltip says why they are disabled.
        for control in (self.pair_combo, self.mode_combo, self.swap_button):
            control.setEnabled(enabled)
            control.setToolTip("" if enabled else strings.LOCKED_TOOLTIP)
        self.voice_lock = None if enabled else strings.LOCKED_TOOLTIP
        self.voice_rows.set_switches_locked(self.voice_lock)
        if enabled:
            self.refresh_availability()
        else:
            self.voice_rows_changed.emit()

    def set_devices_enabled(self, enabled: bool) -> None:
        self.host.device_setup.set_enabled(enabled)
