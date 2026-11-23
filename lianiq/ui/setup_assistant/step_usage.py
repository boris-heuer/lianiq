"""Setup assistant step 1, *What do you want to do?* (CAP-0171 spec §2.2.1 item 2, AC-03).

One checkbox per usage profile (C §7): enabled and experimental profiles are selectable,
planned ones are disabled and marked *Planned*. Text translation is selectable since CAP-0172
(its C §9 row). **Next** needs at least one ticked usage.
"""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QCheckBox, QLabel, QVBoxLayout, QWidget

from lianiq.packs.usage import USAGE_PROFILES, UsageAvailability, UsageProfile
from lianiq.ui import strings

DEFAULT_USAGES = ("conversation",)
_MARKS = {
    UsageAvailability.EXPERIMENTAL: strings.ASSIST_EXPERIMENTAL,
    UsageAvailability.PLANNED: strings.ASSIST_PLANNED,
}


def usage_text(profile: UsageProfile) -> str:
    mark = _MARKS.get(profile.availability)
    return profile.label if mark is None else f"{profile.label} ({mark})"


class UsageStep(QWidget):
    changed = Signal()

    def __init__(self, chosen: Sequence[str] = (), profiles=USAGE_PROFILES) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        title = QLabel(strings.ASSIST_USAGE_TITLE)
        title.setObjectName("panelTitle")
        layout.addWidget(title)
        selectable = {p.id for p in profiles if p.availability is not UsageAvailability.PLANNED}
        ticked = {item for item in chosen if item in selectable} or set(DEFAULT_USAGES)
        self.boxes: dict[str, QCheckBox] = {}
        self.profiles = {profile.id: profile for profile in profiles}
        for profile in profiles:
            box = QCheckBox(usage_text(profile))
            box.setAccessibleName(box.text())
            box.setEnabled(profile.id in selectable)
            box.setChecked(profile.id in selectable and profile.id in ticked)
            box.toggled.connect(self.changed.emit)
            self.boxes[profile.id] = box
            layout.addWidget(box)
        layout.addStretch(1)

    def selected(self) -> tuple[UsageProfile, ...]:
        return tuple(self.profiles[key] for key, box in self.boxes.items() if box.isChecked())

    def complete(self) -> bool:
        return bool(self.selected())
