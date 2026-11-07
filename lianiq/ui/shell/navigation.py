"""The persistent left navigation (CAP-0168 spec §2.3.1).

Checkable stock ``QToolButton``s in an exclusive ``QButtonGroup``, one per registry entry, in
the registry order with Settings bottom-aligned. Planned entries are disabled and suffixed
"Planned"; Call Bridge carries the "Experimental" badge. Each button's accessible name is its
label; the description adds the state. Below 1000 logical px window width the sidebar is a
≈ 56 px icon rail: the labels move to the tooltips, the accessible names stay.

Keyboard: click, Space or Enter selects; Up/Down move the focus within the list (skipping
planned entries); ``MainWindow`` binds Ctrl+1…Ctrl+6 to ``select_index``.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QSize, Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QSizePolicy,
    QStyle,
    QToolButton,
    QVBoxLayout,
)

from lianiq.ui import strings
from lianiq.ui.shell.workspaces import DEFAULT_ENTRIES, EntryState, WorkspaceEntry, WorkspaceId

WIDE_WIDTH = 200
QWIDGETSIZE_MAX = (1 << 24) - 1
RAIL_WIDTH = 56
# The window width below which the sidebar collapses to the icon rail.
RAIL_BELOW = 1000
ICONS = {
    WorkspaceId.CONVERSATION: QStyle.StandardPixmap.SP_MediaVolume,
    WorkspaceId.TEXT_TRANSLATION: QStyle.StandardPixmap.SP_FileDialogContentsView,
    WorkspaceId.LISTEN: QStyle.StandardPixmap.SP_MediaPlay,
    WorkspaceId.CALL_BRIDGE: QStyle.StandardPixmap.SP_DriveNetIcon,
    WorkspaceId.LANGUAGE_PACKS: QStyle.StandardPixmap.SP_DirIcon,
    WorkspaceId.SETTINGS: QStyle.StandardPixmap.SP_FileDialogDetailedView,
}
_NAVIGATION_KEYS = {Qt.Key.Key_Up: -1, Qt.Key.Key_Down: 1}
_SELECT_KEYS = {Qt.Key.Key_Return, Qt.Key.Key_Enter}


def entry_text(item: WorkspaceEntry) -> str:
    """The visible label of an entry: planned and experimental entries name their state."""
    if item.state is EntryState.PLANNED:
        return strings.NAV_ENTRY_BADGE.format(label=item.label, badge=strings.NAV_PLANNED)
    if item.state is EntryState.EXPERIMENTAL:
        return strings.NAV_ENTRY_BADGE.format(label=item.label, badge=strings.NAV_EXPERIMENTAL)
    return item.label


def entry_description(item: WorkspaceEntry) -> str:
    if item.state is EntryState.PLANNED:
        return strings.NAV_PLANNED_DESCRIPTION
    if item.state is EntryState.EXPERIMENTAL:
        return strings.NAV_EXPERIMENTAL
    return ""


class NavigationSidebar(QFrame):
    """Emits ``workspace_selected`` when the user selects an enabled entry."""

    workspace_selected = Signal(object)  # WorkspaceId

    def __init__(self, entries: tuple[WorkspaceEntry, ...] = DEFAULT_ENTRIES) -> None:
        super().__init__()
        self.setObjectName("navigationSidebar")
        self.setAccessibleName(strings.NAV_REGION)
        self.entries = entries
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons: dict[WorkspaceId, QToolButton] = {}
        self._session_owner: WorkspaceId | None = None
        self._compact = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 12, 8, 12)
        layout.setSpacing(4)
        for index, item in enumerate(entries):
            if item.id is WorkspaceId.SETTINGS:
                layout.addStretch(1)  # Settings is bottom-aligned
            button = self._button(item)
            self.group.addButton(button, index)
            self.buttons[item.id] = button
            layout.addWidget(button)
        self.group.idClicked.connect(self._clicked)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        self._apply_mode()

    def _button(self, item: WorkspaceEntry) -> QToolButton:
        button = QToolButton()
        button.setObjectName(f"nav-{item.id.value}")
        button.setCheckable(True)
        button.setAutoRaise(True)
        button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        button.setIcon(self.style().standardIcon(ICONS[item.id]))
        button.setIconSize(QSize(20, 20))
        button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        button.setAccessibleName(item.label)
        button.setAccessibleDescription(entry_description(item))
        button.setEnabled(item.selectable)
        button.installEventFilter(self)
        return button

    # Selection ------------------------------------------------------------------------------

    def current(self) -> WorkspaceId | None:
        checked = self.group.checkedId()
        return self.entries[checked].id if checked >= 0 else None

    def select(self, workspace: WorkspaceId, *, notify: bool = True) -> bool:
        """Select ``workspace``; a planned entry is ignored (``False``)."""
        button = self.buttons.get(workspace)
        if button is None or not button.isEnabled():
            return False
        button.setChecked(True)
        if notify:
            self.workspace_selected.emit(workspace)
        return True

    def select_index(self, index: int) -> bool:
        """Ctrl+1…Ctrl+6: select entry ``index`` (0-based); planned entries are ignored."""
        if not 0 <= index < len(self.entries):
            return False
        return self.select(self.entries[index].id)

    def _clicked(self, index: int) -> None:
        self.workspace_selected.emit(self.entries[index].id)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.KeyPress and watched in self.buttons.values():
            key = event.key()
            if key in _NAVIGATION_KEYS and not event.modifiers():
                self._move_focus(watched, _NAVIGATION_KEYS[key])
                return True
            if key in _SELECT_KEYS:
                watched.click()
                return True
        return super().eventFilter(watched, event)

    def _move_focus(self, button: QToolButton, step: int) -> None:
        """Focus the next enabled entry above or below ``button`` (no wrap-around)."""
        order = [self.buttons[item.id] for item in self.entries]
        index = order.index(button) + step
        while 0 <= index < len(order):
            if order[index].isEnabled():
                order[index].setFocus(Qt.FocusReason.TabFocusReason)
                return
            index += step

    # Layout and state -----------------------------------------------------------------------

    @property
    def compact(self) -> bool:
        return self._compact

    def fit_window_width(self, width: int) -> None:
        """Collapse to the icon rail below ``RAIL_BELOW`` logical px; expand above it."""
        compact = width < RAIL_BELOW
        if compact != self._compact:
            self._compact = compact
            self._apply_mode()
        elif not compact:
            self._fit_wide_width()  # the labels may have been re-polished since

    def set_session_owner(self, workspace: WorkspaceId | None) -> None:
        """Mark the entry whose mode owns the running session (``None``: no session)."""
        self._session_owner = workspace
        self._apply_mode()

    def _apply_mode(self) -> None:
        style = (
            Qt.ToolButtonStyle.ToolButtonIconOnly
            if self._compact
            else Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )
        for item in self.entries:
            button = self.buttons[item.id]
            text = entry_text(item)
            description = entry_description(item)
            if item.id is self._session_owner:
                text = f"{text} {strings.NAV_SESSION_MARKER}"
                description = " · ".join(filter(None, (description, strings.NAV_SESSION_ACTIVE)))
            # "&&": a literal ampersand ("Listen & translate"), not a mnemonic marker.
            button.setText(text.replace("&", "&&"))
            button.setAccessibleDescription(description)
            button.setToolButtonStyle(style)
            # In the rail the label moves to the tooltip; planned entries always explain why.
            tooltip = text if self._compact else ""
            if item.state is EntryState.PLANNED:
                tooltip = (
                    strings.NAV_ENTRY_BADGE.format(
                        label=item.label, badge=strings.NAV_PLANNED_DESCRIPTION
                    )
                    if self._compact
                    else strings.NAV_PLANNED_DESCRIPTION
                )
            button.setToolTip(tooltip)
        margin = 4 if self._compact else 8
        self.layout().setContentsMargins(margin, 12, margin, 12)
        if self._compact:
            self.setFixedWidth(RAIL_WIDTH)
        else:
            self.setMaximumWidth(QWIDGETSIZE_MAX)
            self._fit_wide_width()

    def _fit_wide_width(self) -> None:
        """At least ≈ 200 px, wider when a label needs it, so no label is ever clipped."""
        margins = self.layout().contentsMargins()
        widest = max(button.sizeHint().width() for button in self.buttons.values())
        self.setMinimumWidth(max(WIDE_WIDTH, widest + margins.left() + margins.right()))

    def changeEvent(self, event: QEvent) -> None:
        # A font or style change (stylesheet, text scaling) changes the label widths.
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange) and not self._compact:
            self._fit_wide_width()
        super().changeEvent(event)
