"""Element shapes the real Qt window and the Windows save dialog show (local probes after native run 44267851808).

Read with pywinauto ``backend="uia"`` from ``python -m lianiq``: the sidebar's checkable
QToolButtons are ``CheckBox`` elements; the notice history is an ``Edit`` inside a group box
of the same name; the transcript panels offer no Scroll pattern and show a ``ScrollBar`` only
once the text overflows. In the save dialog the file-name ``Edit`` has ``AutomationId`` 1001
inside the "FileNameControlHost" combo box, and the address toolbar also carries 1001.
"""

from __future__ import annotations

from native_e2e.uia import Node

NAV_ENTRY = "CheckBox"
SAVE_DIALOG = (
    Node("Address: Documents", "ToolBar", automation_id="1001"),
    Node("File name:", "ComboBox", automation_id="FileNameControlHost"),
    Node("File name:", "Edit", automation_id="1001"),
    Node("Cancel", "Button", automation_id="2"),
)


def history(top: tuple[str, ...], log: str) -> list[Node]:
    return [
        Node("Notice history", "Group", value="", parents=top),
        Node("Notice history", "Edit", value=log, parents=(*top, "Notice history")),
    ]


def panel_bars(top: tuple[str, ...], unreadable: bool, scrolled: bool) -> list[Node]:
    """The panels' scroll bars: one without a value, or Translation scrolled to the end."""
    bars = [Node("", "ScrollBar", scroll=None, parents=(*top, "Original"))] if unreadable else []
    if scrolled:
        bars.append(Node("", "ScrollBar", scroll=1.0, parents=(*top, "Translation")))
    return bars
