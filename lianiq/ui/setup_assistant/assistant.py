"""The skippable first-run setup assistant (CAP-0171 spec §2.2.1; C §7, §9, §11).

A stock ``QDialog`` over the main window with the step list (the step titles) and a
``QStackedWidget`` of the four steps: usage, languages, audio check and readiness.
**Skip**, Escape and the close button store ``first_run = "skipped"`` while the first run
is pending (a later run never downgrades a stored choice); **Finish** stores ``completed``,
the ticked usages and the languages, whether or not all is ready. Settings are saved at
once when the window persists them, so the next launch shows no assistant (AC-01).
"""

from __future__ import annotations

import logging
import threading
from dataclasses import replace

from PySide6.QtCore import Signal, Slot
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QListWidget,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
)

from lianiq.ui import strings
from lianiq.ui.setup_assistant.step_audio import AudioStep
from lianiq.ui.setup_assistant.step_languages import LanguagesStep
from lianiq.ui.setup_assistant.step_review import ReviewStep, compute_review, device_readiness
from lianiq.ui.setup_assistant.step_usage import UsageStep

_LOG = logging.getLogger("lianiq.ui.setup_assistant")
TITLES = (
    strings.ASSIST_USAGE_TITLE,
    strings.ASSIST_LANG_TITLE,
    strings.ASSIST_AUDIO_TITLE,
    strings.ASSIST_REVIEW_TITLE,
)
USAGE, LANGUAGES, AUDIO, REVIEW = range(len(TITLES))


class SetupAssistant(QDialog):
    review_ready = Signal(int, object)  # generation, ReadinessReview or None (failed)

    def __init__(self, host) -> None:
        super().__init__(host)
        self.host = host
        self.setWindowTitle(strings.ASSIST_TITLE)
        self.setAccessibleName(strings.ASSIST_TITLE)
        stored, registry = host.config.provisioning, host.pipeline.registry
        self.usage = UsageStep(stored.usages)
        self.languages = LanguagesStep(registry, stored.languages, host.config.languages.pair)
        self.audio = AudioStep(host)
        self.review = ReviewStep(registry, host.language_packs.open_details)
        self.step_list = QListWidget()
        self.step_list.addItems(TITLES)
        self.step_list.setAccessibleName(strings.ASSIST_TITLE)
        self.step_list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.step_list.setMaximumWidth(220)
        self.pages = QStackedWidget()
        for page in (self.usage, self.languages, self.audio, self.review):
            self.pages.addWidget(page)
        self.back_button = QPushButton(strings.ASSIST_BACK)
        self.next_button = QPushButton(strings.ASSIST_NEXT)
        self.skip_button = QPushButton(strings.ASSIST_SKIP)
        self.finish_button = QPushButton(strings.ASSIST_FINISH)
        buttons = QHBoxLayout()
        buttons.addWidget(self.skip_button)
        buttons.addStretch(1)
        for button in (self.back_button, self.next_button, self.finish_button):
            buttons.addWidget(button)
        for button in (self.skip_button, self.back_button, self.next_button, self.finish_button):
            button.setAccessibleName(button.text())
            button.setAutoDefault(False)
        body = QHBoxLayout()
        body.addWidget(self.step_list)
        body.addWidget(self.pages, 1)
        layout = QVBoxLayout(self)
        layout.addLayout(body, 1)
        layout.addLayout(buttons)
        self.back_button.clicked.connect(lambda: self.go(self.pages.currentIndex() - 1))
        self.next_button.clicked.connect(lambda: self.go(self.pages.currentIndex() + 1))
        self.skip_button.clicked.connect(self.reject)
        self.finish_button.clicked.connect(self.accept)
        self.usage.changed.connect(self._update_buttons)
        self.languages.changed.connect(self._update_buttons)
        self.review_ready.connect(self._review_ready)
        host.bridge.packs_event.connect(self._packs_event)
        self._generation = 0
        self.resize(760, 480)
        self.go(USAGE)

    def go(self, index: int) -> None:
        self.pages.setCurrentIndex(index)
        for row in range(self.step_list.count()):
            item = self.step_list.item(row)
            font = item.font()
            font.setBold(row == index)
            item.setFont(font)
        if index == AUDIO:
            self.audio.show_roles(self.usage.selected())
        elif index == REVIEW:
            self.refresh_review()
        self._update_buttons()

    def _update_buttons(self) -> None:
        index = self.pages.currentIndex()
        complete = {USAGE: self.usage.complete(), LANGUAGES: self.languages.complete()}
        self.back_button.setEnabled(index > USAGE)
        self.next_button.setVisible(index < REVIEW)
        self.next_button.setEnabled(complete.get(index, True))
        self.finish_button.setVisible(index == REVIEW)

    # Readiness ---------------------------------------------------------------------------

    def refresh_review(self) -> None:
        """Recompute the review off the Qt thread (the step shows or a pack job ends)."""
        self._generation += 1
        generation, pair = self._generation, self.languages.pair()
        usages, devices = self.usage.selected(), device_readiness(self.host)
        self.review.clear()

        def run() -> None:
            try:
                review = compute_review(self.host, usages, pair, devices)
            except Exception as error:  # noqa: BLE001 - shown in the step
                _LOG.warning("readiness review failed error=%s", error.__class__.__name__)
                review = None
            try:
                self.review_ready.emit(generation, review)
            except RuntimeError:  # the assistant was closed meanwhile
                pass

        threading.Thread(target=run, name="assistant-review", daemon=True).start()

    @Slot(int, object)
    def _review_ready(self, generation: int, review) -> None:
        if generation != self._generation:
            return
        if review is None:
            self.review.space.setText(strings.PACKS_STATUS_FAILED)
            return
        pair, meeting = self.languages.pair(), self.host.config.meeting.local_language
        self.review.show_review(review, meeting if meeting in pair else pair.first)

    @Slot(object)
    def _packs_event(self, event: tuple) -> None:
        if event[0] in ("finished", "failed") and self.pages.currentIndex() == REVIEW:
            self.refresh_review()

    # Skip and Finish ---------------------------------------------------------------------

    def _store(self, **changes) -> None:
        config = self.host.config
        config.provisioning = replace(config.provisioning, **changes)
        if self.host.persist_settings:
            config.save()

    def reject(self) -> None:
        """**Skip**, Escape or the close button."""
        if self.host.config.provisioning.first_run == "pending":
            self._store(first_run="skipped")
        super().reject()

    def accept(self) -> None:
        """**Finish**: the choices are stored whether or not everything is ready."""
        pair = self.languages.pair()
        self._store(
            first_run="completed",
            usages=tuple(profile.id for profile in self.usage.selected()),
            languages=tuple(str(item) for item in pair.members) if pair else (),
        )
        super().accept()
