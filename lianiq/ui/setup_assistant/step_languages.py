"""Setup assistant step 2, *Conversation languages* (CAP-0171 spec §2.2.1 item 3, AC-04).

Two lists from the language registry: qualified languages are selectable, planned ones are
listed disabled with *Planned*. The stored languages, else the configured pair, else the
first two qualified languages are preselected. **Next** needs two different qualified ones.
"""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from lianiq.languages.registry import Availability, LanguagePair, LanguageRegistry
from lianiq.ui import strings

ID_ROLE = Qt.ItemDataRole.UserRole


def _preselected(registry: LanguageRegistry, wanted: Sequence[Sequence[str]]) -> list[str]:
    qualified = [d.id for d in registry.languages() if d.availability is Availability.QUALIFIED]
    for choice in wanted:
        if len(choice) == 2 and choice[0] != choice[1] and all(c in qualified for c in choice):
            return list(choice)
    return qualified[:2]


class LanguagesStep(QWidget):
    changed = Signal()

    def __init__(self, registry: LanguageRegistry, *wanted: Sequence[str]) -> None:
        super().__init__()
        self.registry = registry
        layout = QVBoxLayout(self)
        title = QLabel(strings.ASSIST_LANG_TITLE)
        title.setObjectName("panelTitle")
        layout.addWidget(title)
        lists = QHBoxLayout()
        layout.addLayout(lists, 1)
        chosen = _preselected(registry, wanted)
        self.lists: list[QListWidget] = []
        for index, name in enumerate((strings.ASSIST_LANG_FIRST, strings.ASSIST_LANG_SECOND)):
            column = QVBoxLayout()
            caption = QLabel(name)
            widget = QListWidget()
            widget.setAccessibleName(name)
            caption.setBuddy(widget)
            for definition in registry.languages():
                qualified = definition.availability is Availability.QUALIFIED
                text = definition.english_name
                item = QListWidgetItem(text if qualified else f"{text} — {strings.ASSIST_PLANNED}")
                item.setData(ID_ROLE, str(definition.id))
                if not qualified:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
                widget.addItem(item)
                if index < len(chosen) and str(definition.id) == chosen[index]:
                    widget.setCurrentItem(item)
            widget.currentItemChanged.connect(lambda *_: self.changed.emit())
            column.addWidget(caption)
            column.addWidget(widget, 1)
            lists.addLayout(column)
            self.lists.append(widget)

    def languages(self) -> tuple[str, ...]:
        items = [widget.currentItem() for widget in self.lists]
        return tuple(item.data(ID_ROLE) for item in items if item is not None)

    def pair(self) -> LanguagePair | None:
        chosen = self.languages()
        if len(chosen) != 2 or chosen[0] == chosen[1]:
            return None
        try:
            return self.registry.pair(*chosen)
        except ValueError:  # a planned language cannot form a pair
            return None

    def complete(self) -> bool:
        return self.pair() is not None
