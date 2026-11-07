"""The session strip (CAP-0168 spec §2.3.2): the running session and **Stop (F9)**.

Sits at the bottom of the workspace area, outside the page stack, so it stays visible in
every workspace while the active-session owner is not idle: "<Mode> starting… / running /
stopping…" and **Stop (F9)**, which stops the active session from any workspace. While idle
the strip is hidden and **Stop** is disabled, so a focus return never targets it.
"""

from __future__ import annotations

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton

from lianiq.ui import strings
from lianiq.ui.shell.session_owner import SessionState
from lianiq.ui.shell.workspaces import WorkspaceId, label

STATE_TEXT = {
    SessionState.STARTING: strings.SESSION_STARTING,
    SessionState.RUNNING: strings.SESSION_RUNNING,
    SessionState.STOPPING: strings.SESSION_STOPPING,
}


class SessionStrip(QFrame):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("sessionStrip")
        self.setAccessibleName(strings.SESSION_STRIP_NAME)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 6, 12, 6)
        self.state_label = QLabel()
        self.state_label.setObjectName("sessionState")
        self.stop_button = QPushButton(strings.STOP_ACTION)
        self.stop_button.setObjectName("stopButton")
        self.stop_button.setAccessibleName(strings.STOP_ACTION)
        layout.addWidget(self.state_label, 1)
        layout.addWidget(self.stop_button)
        self.show_state(SessionState.IDLE, None)

    def show_state(self, state: SessionState, active: WorkspaceId | None) -> None:
        """Follow the active-session owner (``ActiveSessionOwner.subscribe``)."""
        if state is SessionState.IDLE or active is None:
            self.stop_button.setEnabled(False)
            self.state_label.clear()
            self.hide()
            return
        text = STATE_TEXT[state].format(mode=label(active))
        self.state_label.setText(text)
        self.setAccessibleDescription(text)
        self.stop_button.setEnabled(state is not SessionState.STOPPING)
        self.show()
