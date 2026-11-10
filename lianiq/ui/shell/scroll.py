"""The workspace scroll area (CAP-0168 spec §2.3.7).

Workspace content scrolls when the window (or the available work area) is smaller than the
content's minimum; Start/Stop and the session strip stay outside the scroll area. The area
itself is not a Tab stop; ``MainWindow`` scrolls a control into view when Tab reaches it.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QScrollArea, QWidget


def workspace_scroll(content: QWidget) -> QScrollArea:
    """``content`` in a frameless, resizable scroll area that never takes focus itself."""
    area = QScrollArea()
    area.setObjectName("workspaceScroll")
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.Shape.NoFrame)
    area.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    content.setObjectName(content.objectName() or "workspaceContent")
    area.setWidget(content)
    return area


def scroll_area_of(widget: QWidget | None) -> QScrollArea | None:
    """The workspace scroll area that contains ``widget``, if any."""
    while widget is not None:
        if isinstance(widget, QScrollArea) and widget.objectName() == "workspaceScroll":
            return widget
        widget = widget.parentWidget()
    return None
