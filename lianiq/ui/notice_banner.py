"""The notice banner at the top of each workspace (CAP-0168 spec §2.3.4).

Shows the workspace's top notice (``NoticeCenter.top``) with its actions, and "+N more"
(``NOTICE_MORE``) when further notices are live; "+N more" opens Settings › Diagnostics.
Severity is carried by text (the severity word), icon (stock message-box icons) and colour
(the ``severity`` property for the stylesheet). A non-blocking notice can be dismissed; a
blocking one only clears by its own resolution.

A banner change is announced to assistive technology by changing the banner's accessible
name and description, never by moving focus. ``QWidget.setAccessibleName`` and
``setAccessibleDescription`` themselves send the ``NameChanged`` / ``DescriptionChanged``
event through ``QAccessible.updateAccessibility`` (Qt's ``qwidget.cpp``), so the banner
does not send a second, duplicate event.

Focus only moves when the focused banner control disappears: while the banner stays, focus
goes to the banner frame; when the last notice is resolved and the banner hides, focus goes
to ``focus_fallback()`` (the workspace's sidebar entry), never to Qt's arbitrary next widget.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from lianiq.ui import strings
from lianiq.ui.notices import Notice, NoticeAction, NoticeCenter, Severity
from lianiq.ui.shell.workspaces import WorkspaceId

SEVERITY_TEXT = {
    Severity.INFO: strings.NOTICE_INFO,
    Severity.WARNING: strings.NOTICE_WARNING,
    Severity.BLOCKING: strings.NOTICE_BLOCKING,
}
SEVERITY_ICON = {
    Severity.INFO: QStyle.StandardPixmap.SP_MessageBoxInformation,
    Severity.WARNING: QStyle.StandardPixmap.SP_MessageBoxWarning,
    Severity.BLOCKING: QStyle.StandardPixmap.SP_MessageBoxCritical,
}


def button_text(text: str) -> str:
    """A literal button label: ``&`` would otherwise become a mnemonic."""
    return text.replace("&", "&&")


def accessible_name(notice: Notice) -> str:
    title = notice.title
    if notice.repeats:
        title = strings.NOTICE_REPEATED.format(title=title, count=notice.repeats + 1)
    return strings.NOTICE_ACCESSIBLE_NAME.format(
        severity=SEVERITY_TEXT[notice.severity], title=title
    )


def accessible_description(notice: Notice) -> str:
    return strings.NOTICE_ACCESSIBLE_DESCRIPTION.format(
        source=notice.source, continues=notice.continues, detail=notice.detail
    ).strip()


class NoticeBanner(QFrame):
    more_requested = Signal()  # "+N more": open Settings › Diagnostics

    def __init__(self, center: NoticeCenter, workspace: WorkspaceId) -> None:
        super().__init__()
        self.center = center
        self.workspace = workspace
        self.notice: Notice | None = None
        # The stable control that gets focus when the banner hides with focus inside it.
        self.focus_fallback: Callable[[], QWidget | None] | None = None
        self.setObjectName("noticeBanner")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        # The banner itself takes focus when a focused banner button disappears.
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 8, 12, 8)
        row.setSpacing(10)
        self.icon_label = QLabel()
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        row.addWidget(self.icon_label)
        texts = QVBoxLayout()
        texts.setSpacing(2)
        self.title_label = QLabel()
        self.title_label.setObjectName("noticeTitle")
        self.title_label.setWordWrap(True)
        self.title_label.setTextFormat(Qt.TextFormat.PlainText)
        self.detail_label = QLabel()
        self.detail_label.setObjectName("noticeDetail")
        self.detail_label.setWordWrap(True)
        self.detail_label.setTextFormat(Qt.TextFormat.PlainText)
        texts.addWidget(self.title_label)
        texts.addWidget(self.detail_label)
        row.addLayout(texts, 1)
        self.actions_row = QHBoxLayout()
        self.actions_row.setSpacing(6)
        row.addLayout(self.actions_row)
        self.action_buttons: list[QPushButton] = []
        self.dismiss_button = QPushButton(strings.NOTICE_DISMISS)
        self.dismiss_button.clicked.connect(self._dismiss)
        self.more_button = QPushButton()
        self.more_button.clicked.connect(self.more_requested.emit)
        row.addWidget(self.dismiss_button)
        row.addWidget(self.more_button)
        self.setAccessibleName(strings.NOTICE_REGION)
        self.hide()
        center.subscribe(lambda _change, _notice: self.refresh())

    def refresh(self) -> None:
        """Show the current top notice; announce a change through accessibility only."""
        top = self.center.top(self.workspace)
        self._keep_focus(top)
        self.notice = top
        if top is None:
            self._clear_actions()
            self.hide()
            self._set_accessible(strings.NOTICE_REGION, "")
            return
        self.setProperty("severity", top.severity.name.lower())
        self.style().unpolish(self)
        self.style().polish(self)
        icon = self.style().standardIcon(SEVERITY_ICON[top.severity])
        self.icon_label.setPixmap(icon.pixmap(24, 24))
        name = accessible_name(top)
        self.title_label.setText(name)
        self.detail_label.setText(accessible_description(top))
        self._show_actions(top.actions)
        self.dismiss_button.setVisible(top.severity is not Severity.BLOCKING)
        more = self.center.count(self.workspace) - 1
        self.more_button.setText(button_text(strings.NOTICE_MORE.format(count=more)))
        self.more_button.setAccessibleName(strings.NOTICE_MORE.format(count=more))
        self.more_button.setVisible(more > 0)
        self.show()
        self._set_accessible(name, accessible_description(top))

    def update_action_states(self) -> None:
        """Re-evaluate each action's ``enabled`` (e.g. **Reconnect** after Stop)."""
        if self.notice is None:
            return
        for button, action in zip(self.action_buttons, self.notice.actions, strict=False):
            self._apply_state(button, action)

    # Internals ------------------------------------------------------------------------------

    def _show_actions(self, actions: tuple[NoticeAction, ...]) -> None:
        # The same actions (e.g. a repeated post after **Retry**) keep their buttons, so a
        # focused button keeps focus; each click runs the current notice's callback.
        if [b.accessibleName() for b in self.action_buttons] != [a.label for a in actions]:
            self._clear_actions()
            for index, action in enumerate(actions):
                button = QPushButton(button_text(action.label))
                button.setAccessibleName(action.label)
                button.clicked.connect(lambda _checked=False, index=index: self._run(index))
                self.actions_row.addWidget(button)
                self.action_buttons.append(button)
        for button, action in zip(self.action_buttons, actions, strict=True):
            self._apply_state(button, action)

    def _run(self, index: int) -> None:
        if self.notice is not None and index < len(self.notice.actions):
            action = self.notice.actions[index]
            if action.available():
                action.callback()

    @staticmethod
    def _apply_state(button: QPushButton, action: NoticeAction) -> None:
        available = action.available()
        button.setEnabled(available)
        hint = "" if available else action.disabled_hint
        button.setToolTip(hint)
        button.setAccessibleDescription(hint)

    def _clear_actions(self) -> None:
        for button in self.action_buttons:
            self.actions_row.removeWidget(button)
            button.hide()
            button.deleteLater()
        self.action_buttons = []

    def _keep_focus(self, top: Notice | None) -> None:
        """Move focus deliberately when the focused banner control is about to disappear."""
        focus = QApplication.focusWidget() or self.window().focusWidget()
        if focus is None or not (focus is self or self.isAncestorOf(focus)):
            return
        if top is None:  # the banner hides: a stable control outside it
            target = self.focus_fallback() if self.focus_fallback is not None else None
            if target is not None:
                target.setFocus(Qt.FocusReason.OtherFocusReason)
            return
        keeps_actions = [a.label for a in top.actions] == [
            b.accessibleName() for b in self.action_buttons
        ]
        disappears = (
            (focus in self.action_buttons and not keeps_actions)
            or (focus is self.dismiss_button and top.severity is Severity.BLOCKING)
            or (focus is self.more_button and self.center.count(self.workspace) <= 1)
        )
        if disappears:
            self.setFocus(Qt.FocusReason.OtherFocusReason)

    def _dismiss(self) -> None:
        if self.notice is not None and self.notice.severity is not Severity.BLOCKING:
            self.center.resolve(self.notice.key)

    def _set_accessible(self, name: str, description: str) -> None:
        # Each setter sends its own accessibility update event (see the module docstring).
        if self.accessibleName() != name:
            self.setAccessibleName(name)
        if self.accessibleDescription() != description:
            self.setAccessibleDescription(description)
