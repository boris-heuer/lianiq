"""Element shapes the real Qt window and the Windows save dialog show (local probes after native run 44267851808).

Read with pywinauto ``backend="uia"`` from ``python -m lianiq``: the sidebar's checkable
QToolButtons are ``CheckBox`` elements; the notice history is an ``Edit`` inside a group box
of the same name; the *Transcript* list is read like the former transcript panels: no Scroll pattern, a
``ScrollBar`` only once the rows overflow. In the save dialog the file-name ``Edit`` has ``AutomationId`` 1001
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
# The "already exists, replace?" task dialog inside the save dialog (a German UI shows
# "Speichern unter bestätigen" with "Ja" and "Nein"; the AutomationIds do not change).
_PROMPT = ("Export diagnostics", "Confirm Save As")
REPLACE_PROMPT = (
    Node("Confirm Save As", "Window", parents=_PROMPT[:1]),
    Node("diagnostics-E10.txt already exists.", "Text", automation_id="ContentText",
         parents=_PROMPT),
    Node("Yes", "Button", automation_id="CommandButton_6", parents=_PROMPT),
    Node("No", "Button", automation_id="CommandButton_7", parents=_PROMPT),
)  # fmt: skip


def history(top: tuple[str, ...], log: str) -> list[Node]:
    return [
        Node("Notice history", "Group", value="", parents=top),
        Node("Notice history", "Edit", value=log, parents=(*top, "Notice history")),
    ]


LIST = "Transcript"


def _lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.strip()]


def transcript_rows(original: str, translation: str, top: tuple[str, ...]) -> list[Node]:
    """One *Transcript* row per line pair "{source}: …" / "{target}: …" (accessible text)."""
    rows = []
    for index, (said, heard) in enumerate(zip(_lines(original), _lines(translation))):
        source, _, text = said.partition(": ")
        target, _, translated = heard.partition(": ")
        name = f"12:00:{index:02d}, {source}: {text}. {target}: {translated}"
        rows.append(Node(name, "ListItem", parents=(*top, LIST)))
    return rows


def transcript_list(
    top: tuple[str, ...],
    original: str = "",
    translation: str = "",
    rect: tuple[int, int, int, int] = (0, 0, 0, 0),
    unreadable: bool = False,
    scrolled: bool = False,
) -> list[Node]:
    """The Conversation *Transcript* list, its rows and its scroll bar: one without a value,
    or one scrolled to the end (the list offers no Scroll pattern, as the panels did)."""
    bars = [Node("", "ScrollBar", scroll=None, parents=(*top, LIST))] if unreadable else []
    if scrolled:
        bars.append(Node("", "ScrollBar", scroll=1.0, parents=(*top, LIST)))
    return [
        Node(LIST, "List", rect=rect, parents=top),
        *transcript_rows(original, translation, top),
        *bars,
    ]
