"""The Listen & translate page widgets (CAP-0170 spec §2.1, §2.3).

``ListenWorkspace`` base (file-size split): the setup row (source, swap, target,
microphone), the readiness line with its link, the action row (Start, state, level) and the
``PairedTranscriptView`` (list, *New turns below* with **Jump to latest**, per-turn copy and
the transcript actions with **Clear transcript**).
Stock widgets styled by ``theme.py``; every control has an accessible name
equal to its label; Tab follows creation order: setup row → Start → transcript → actions.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from lianiq.ui import strings
from lianiq.ui.transcript.view import PairedTranscriptView
from lianiq.ui.workspaces.text_translation_layout import fill_languages


def _button(text: str, name: str | None = None) -> QPushButton:
    button = QPushButton(text)
    button.setAccessibleName(text)
    if name:
        button.setObjectName(name)
    return button


def _combo(row: QHBoxLayout, label: str) -> QComboBox:
    caption = QLabel(label)
    combo = QComboBox()
    combo.setAccessibleName(label)
    combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
    caption.setBuddy(combo)
    row.addWidget(caption)
    row.addWidget(combo)
    return combo


class ListenLayout:
    """Builds the page; ``ListenWorkspace`` wires and renders it."""

    def build_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("listenPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        setup = QHBoxLayout()
        self.source_combo = _combo(setup, strings.LISTEN_SOURCE_LANGUAGE)
        self.swap_button = _button(strings.LISTEN_SWAP)
        setup.addWidget(self.swap_button)
        self.target_combo = _combo(setup, strings.LISTEN_TARGET_LANGUAGE)
        for combo in (self.source_combo, self.target_combo):
            fill_languages(combo, self.registry)
        self.microphone_combo = _combo(setup, strings.LISTEN_MICROPHONE)
        setup.addStretch(1)
        layout.addLayout(setup)

        readiness = QHBoxLayout()
        self.readiness_label = QLabel()
        self.readiness_label.setObjectName("listenReadiness")
        self.readiness_label.setWordWrap(True)
        self.open_packs_button = _button(strings.PACKS_OPEN)
        self.open_audio_button = _button(strings.TEXT_OPEN_AUDIO)
        readiness.addWidget(self.readiness_label, 1)
        readiness.addWidget(self.open_packs_button)
        readiness.addWidget(self.open_audio_button)
        layout.addLayout(readiness)

        actions = QHBoxLayout()
        self.start_button = _button(strings.LISTEN_START, "primaryButton")
        self.state_label = QLabel(strings.LISTEN_STATE_READY)
        self.state_label.setObjectName("listenState")
        self.level_bar = QProgressBar()
        self.level_bar.setRange(0, 100)
        self.level_bar.setTextVisible(False)
        self.level_bar.setMaximumWidth(160)
        self.level_bar.setAccessibleName(strings.LISTEN_MICROPHONE)
        actions.addWidget(self.start_button)
        actions.addWidget(self.state_label)
        actions.addWidget(self.level_bar)
        actions.addStretch(1)
        layout.addLayout(actions)

        # The paired transcript view (paired-transcript spec §3.4): list, Jump, per-turn
        # copy actions and Copy, Export and Clear transcript.
        view = PairedTranscriptView(
            self.controller.transcript, self.registry, strings.TRANSCRIPT_CLEAR, self
        )
        view.set_placeholder(strings.LISTEN_EMPTY)
        layout.addWidget(view, 1)
        self.paired_view, self.model, self.transcript_view = view, view.model, view.list
        self.empty_label, self.new_below_label = view.placeholder, view.new_below_label
        self.jump_button, self.clear_button = view.jump_button, view.clear_button
        self.copy_button, self.export_button = view.copy_all_button, view.export_button
        self.page = page
        return page
