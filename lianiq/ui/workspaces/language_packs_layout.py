"""The Language packs page layout (CAP-0171 spec §2.3; file-size split of ``language_packs``).

Header (title, ``PACKS_FOLDER``), the empty-state hint, one group per pack kind with a
``PackRow`` per catalog pack (unsupported registry rows as text), and the collapsed
*Planned languages* group without actions. Tab order: header → rows → row actions.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGroupBox, QLabel, QMessageBox, QToolButton, QVBoxLayout, QWidget

from lianiq.languages.capabilities import DirectedEdge
from lianiq.languages.registry import LanguageRegistry
from lianiq.packs.catalog import PackCatalog, PackKind
from lianiq.packs.jobs import PackJobRunner
from lianiq.packs.state import LanguageRow, PackState, language_rows
from lianiq.ui import strings
from lianiq.ui.shell.scroll import workspace_scroll
from lianiq.ui.workspaces.language_packs_rows import (
    STATE_TEXT,
    PackRow,
    Sessions,
    needed_by,
    pack_languages,
)
from lianiq.ui.workspaces.settings import read_only_value

GROUPS = (
    (PackKind.RECOGNITION, strings.PACKS_GROUP_RECOGNITION),
    (PackKind.TRANSLATION, strings.PACKS_GROUP_TRANSLATION),
    (PackKind.VOICE, strings.PACKS_GROUP_VOICES),
)
RowActions = Callable[[str], dict[str, Callable[[], None]]]


def confirm_remove(parent: QWidget, text: str) -> bool:
    buttons = QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel
    answer = QMessageBox.question(parent, strings.PACK_REMOVE, text, buttons)
    return answer == QMessageBox.StandardButton.Yes


class Listener:
    """Hands the runner's worker-thread calls to the Qt thread through the bridge."""

    def __init__(self, emit, runner: PackJobRunner, pack_id: str) -> None:
        self.emit, self.runner, self.pack_id = emit, runner, pack_id

    def progress(self, view) -> None:
        self.emit(("progress", view))

    def finished(self, result) -> None:  # ``result`` is None after a remove
        self.emit(("finished", self.pack_id))

    def failed(self, pack_id: str, reason: str) -> None:
        self.emit(("failed", pack_id, reason, self.runner.last_error))


def _subject_name(row: LanguageRow, registry: LanguageRegistry) -> str:
    if isinstance(row.subject, DirectedEdge):
        return strings.ROUTING_FIXED.format(
            source=registry.get(row.subject.source).english_name,
            target=registry.get(row.subject.target).english_name,
        )
    return registry.get(row.subject).english_name


def _text(text: str) -> QLabel:
    label = QLabel(text)
    label.setAccessibleName(text)
    return label


class LanguagePacksLayout:
    """Builds the page; ``rows`` maps pack id → ``PackRow``."""

    def __init__(self, registry: LanguageRegistry, packs: PackCatalog, sessions: Sessions) -> None:
        self.registry, self.packs, self.sessions = registry, packs, sessions
        self.rows: dict[str, PackRow] = {}
        self.planned_names: list[str] = []

    def build(self, actions: RowActions) -> QWidget:
        page = QWidget()
        page.setObjectName("languagePacksPage")
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        content = QWidget()
        page_layout.addWidget(workspace_scroll(content), 1)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        heading = QLabel(strings.PACKS_TITLE)
        heading.setObjectName("panelTitle")
        layout.addWidget(heading)
        self.folder_label = read_only_value(strings.PACKS_TITLE)
        self.folder_label.setWordWrap(True)  # a long models path never scrolls sideways
        layout.addWidget(self.folder_label)
        self.status_message = _text(strings.PACKS_STATUS_FAILED)
        self.status_message.setVisible(False)
        layout.addWidget(self.status_message)
        self.empty_hint = _text(strings.PACK_EMPTY_HINT)
        self.empty_hint.setVisible(False)
        layout.addWidget(self.empty_hint)
        all_rows = language_rows(self.registry, self.packs)
        for kind, title in GROUPS:
            group = QGroupBox(title)
            group.setAccessibleName(title)
            column = QVBoxLayout(group)
            for row in all_rows:
                if row.kind is not kind or row.state is PackState.PLANNED:
                    continue
                if row.pack_id is None:  # a qualified capability without a catalog pack
                    name = _subject_name(row, self.registry)
                    column.addWidget(_text(f"{name} — {STATE_TEXT[row.state]}"))
                elif row.pack_id not in self.rows:
                    pack = self.packs.get(row.pack_id)
                    needed = needed_by(pack.id, self.packs, self.sessions)
                    languages = pack_languages(pack, self.registry)
                    self.rows[pack.id] = PackRow(pack, languages, needed, actions(pack.id))
                    column.addWidget(self.rows[pack.id])
            layout.addWidget(group)
        layout.addWidget(self._planned(all_rows))
        layout.addStretch(1)
        return page

    def _planned(self, all_rows: tuple[LanguageRow, ...]) -> QWidget:
        """*Planned languages*: collapsed, one line per planned language, no actions."""
        box = QWidget()
        column = QVBoxLayout(box)
        column.setContentsMargins(0, 0, 0, 0)
        self.planned_toggle = QToolButton()
        self.planned_toggle.setText(strings.PACKS_GROUP_PLANNED)
        self.planned_toggle.setAccessibleName(strings.PACKS_GROUP_PLANNED)
        self.planned_toggle.setCheckable(True)
        self.planned_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.planned_toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.planned_list = QWidget()
        items = QVBoxLayout(self.planned_list)
        for row in all_rows:
            planned = row.state is PackState.PLANNED and row.kind is PackKind.RECOGNITION
            if planned and not isinstance(row.subject, DirectedEdge):
                name = _subject_name(row, self.registry)
                self.planned_names.append(name)
                items.addWidget(_text(f"{name} — {strings.PACK_STATE_PLANNED}"))
        self.planned_list.setVisible(False)
        self.planned_toggle.toggled.connect(self._toggle_planned)
        column.addWidget(self.planned_toggle)
        column.addWidget(self.planned_list)
        return box

    def _toggle_planned(self, shown: bool) -> None:
        self.planned_list.setVisible(shown)
        arrow = Qt.ArrowType.DownArrow if shown else Qt.ArrowType.RightArrow
        self.planned_toggle.setArrowType(arrow)
