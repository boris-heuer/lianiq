"""The Text translation page widgets (CAP-0172 spec §2.1, §2.3).

``TextTranslationWorkspace`` base (file-size split). Language row on top, the splitter with
*Source text* left and *Translation* right, the action row below. Stock widgets styled by
``theme.py``; every control has an accessible name equal to its label, and the Tab order
follows the creation order: language row → source → result → action row.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from lianiq.languages.registry import Availability, LanguageRegistry
from lianiq.ui import strings
from lianiq.ui.workspaces.pair_selection import add_disabled_item


def _auto_direction(editor: QPlainTextEdit) -> None:
    """Each paragraph follows its own text direction, so RTL paragraphs run right to left."""
    document = editor.document()
    option = document.defaultTextOption()
    option.setTextDirection(Qt.LayoutDirection.LayoutDirectionAuto)
    document.setDefaultTextOption(option)


def _button(text: str, name: str | None = None) -> QPushButton:
    button = QPushButton(text)
    button.setAccessibleName(text)
    if name:
        button.setObjectName(name)
    return button


def fill_languages(combo: QComboBox, registry: LanguageRegistry) -> None:
    """Every registry language by English name; planned ones disabled with the suffix."""
    combo.blockSignals(True)
    combo.clear()
    for item in registry.languages():
        if item.availability is Availability.PLANNED:
            add_disabled_item(combo, f"{item.english_name} {strings.PAIR_PLANNED_SUFFIX}")
        else:
            combo.addItem(item.english_name, item.id)
    combo.blockSignals(False)


class TextTranslationLayout:
    """Builds the page; ``TextTranslationWorkspace`` wires and renders it."""

    def build_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("textTranslationPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addLayout(self._language_row())
        readiness_row = QHBoxLayout()
        self.readiness_label = QLabel()
        self.readiness_label.setObjectName("textReadiness")
        self.readiness_label.setWordWrap(True)
        self.readiness_packs_button = _button(strings.PACKS_OPEN)  # translation pack missing
        readiness_row.addWidget(self.readiness_label, 1)
        readiness_row.addWidget(self.readiness_packs_button)
        layout.addLayout(readiness_row)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.addWidget(self._source_pane())
        self.splitter.addWidget(self._result_pane())
        layout.addWidget(self.splitter, 1)
        layout.addLayout(self._action_row())
        self.page = page
        return page

    def _language_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self.source_combo = self._language_combo(row, strings.TEXT_SOURCE_LANGUAGE)
        self.swap_button = _button(strings.TEXT_SWAP)
        row.addWidget(self.swap_button)
        self.target_combo = self._language_combo(row, strings.TEXT_TARGET_LANGUAGE)
        row.addStretch(1)
        return row

    def _language_combo(self, row: QHBoxLayout, label: str) -> QComboBox:
        caption = QLabel(label)
        combo = QComboBox()
        combo.setAccessibleName(label)
        combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        caption.setBuddy(combo)
        fill_languages(combo, self.registry)
        row.addWidget(caption)
        row.addWidget(combo)
        return combo

    def _pane(self, title: str) -> tuple[QWidget, QVBoxLayout, QPlainTextEdit]:
        pane = QWidget()
        column = QVBoxLayout(pane)
        column.setContentsMargins(0, 0, 0, 0)
        caption = QLabel(title)
        caption.setObjectName("panelTitle")
        editor = QPlainTextEdit()
        editor.setAccessibleName(title)
        _auto_direction(editor)
        caption.setBuddy(editor)
        column.addWidget(caption)
        column.addWidget(editor, 1)
        return pane, column, editor

    def _source_pane(self) -> QWidget:
        pane, column, self.source_edit = self._pane(strings.TEXT_SOURCE_LABEL)
        self.source_edit.setPlaceholderText(strings.TEXT_SOURCE_PLACEHOLDER)
        row = QHBoxLayout()
        self.counter_label = QLabel()
        self.counter_label.setObjectName("textCounter")
        self.copy_source_button = _button(strings.TEXT_COPY_SOURCE)
        row.addWidget(self.counter_label, 1)
        row.addWidget(self.copy_source_button)
        column.addLayout(row)
        return pane

    def _result_pane(self) -> QWidget:
        pane, column, self.result_edit = self._pane(strings.TEXT_RESULT_LABEL)
        self.result_edit.setReadOnly(True)
        self.result_edit.setPlaceholderText(strings.TEXT_RESULT_EMPTY)
        self.stale_label = QLabel(strings.TEXT_STALE)
        self.stale_label.setObjectName("textStale")
        self.stale_label.setWordWrap(True)
        self.stale_label.hide()
        column.insertWidget(1, self.stale_label)
        row = QHBoxLayout()
        self.status_label = QLabel()
        self.status_label.setObjectName("textStatus")
        self.status_label.setWordWrap(True)
        self.copy_translation_button = _button(strings.TEXT_COPY_TRANSLATION)
        self.busy_indicator = QProgressBar()  # indeterminate while a request runs
        self.busy_indicator.setObjectName("textBusy")
        self.busy_indicator.setRange(0, 0)
        self.busy_indicator.setTextVisible(False)
        self.busy_indicator.setMaximumWidth(120)
        self.busy_indicator.setAccessibleName(strings.TEXT_TRANSLATING)
        self.busy_indicator.hide()
        row.addWidget(self.busy_indicator)
        row.addWidget(self.status_label, 1)
        row.addWidget(self.copy_translation_button)
        column.addLayout(row)
        self.no_pack_button = _button(strings.PACKS_OPEN)  # with TEXT_NO_PACK_HINT
        self.no_pack_button.hide()
        column.insertWidget(3, self.no_pack_button, 0, Qt.AlignmentFlag.AlignLeft)
        return pane

    def _action_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self.translate_button = _button(strings.TEXT_TRANSLATE, "primaryButton")
        self.translate_button.setToolTip(strings.TEXT_TRANSLATE_HINT)
        self.retry_button = _button(strings.TEXT_RETRY)
        self.retry_button.hide()
        self.play_button = _button(strings.TEXT_PLAY)  # Play translation / Replay / Stop
        self.play_hint = QLabel()  # voice or speakers missing
        self.play_hint.setObjectName("textPlayHint")
        self.play_hint.setWordWrap(True)
        self.open_audio_button = _button(strings.TEXT_OPEN_AUDIO)
        self.voice_packs_button = _button(strings.PACKS_OPEN)  # target voice missing
        for widget in (self.translate_button, self.retry_button, self.play_button):
            row.addWidget(widget)
        row.addWidget(self.play_hint, 1)
        row.addWidget(self.open_audio_button)
        row.addWidget(self.voice_packs_button)
        return row
