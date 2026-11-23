"""The Listen & translate page widgets (CAP-0170 spec §2.1, §2.3).

``ListenWorkspace`` base (file-size split): the setup row (source, swap, target,
microphone), the readiness line with its link, the action row (Start, state, level) and the
transcript list, then *New segments below* with **Jump to latest** and the transcript actions.
Stock widgets styled by ``theme.py``; every control has an accessible name
equal to its label; Tab follows creation order: setup row → Start → transcript → actions.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListView,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from lianiq.ui import strings
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

        self.empty_label = QLabel(strings.LISTEN_EMPTY)
        self.empty_label.setObjectName("listenEmpty")
        self.empty_label.setWordWrap(True)
        self.transcript_view = QListView()
        self.transcript_view.setAccessibleName(strings.LISTEN_TRANSCRIPT)
        self.transcript_view.setWordWrap(True)
        self.transcript_view.setUniformItemSizes(False)
        self.transcript_view.setSpacing(4)
        layout.addWidget(self.empty_label)
        layout.addWidget(self.transcript_view, 1)

        bottom = QHBoxLayout()
        self.new_below_label = QLabel(strings.LISTEN_NEW_BELOW)
        self.new_below_label.setObjectName("listenNewBelow")
        self.jump_button = _button(strings.LISTEN_JUMP)
        self.copy_button = _button(strings.LISTEN_COPY)
        self.export_button = _button(strings.LISTEN_EXPORT)
        for widget in (self.new_below_label, self.jump_button):
            bottom.addWidget(widget)
        bottom.addStretch(1)
        bottom.addWidget(self.copy_button)
        bottom.addWidget(self.export_button)
        layout.addLayout(bottom)
        self.page = page
        return page
