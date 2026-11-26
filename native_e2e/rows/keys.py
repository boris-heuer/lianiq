"""Keyboard steps shared by the rows E-31, E-32 and E-33 (automated-po-rows spec §2.2).

``walk`` turns ``ui.tab_walk`` into a check: it passes when the focus cycle closed and every
stop had a non-empty UIA name. Its detail holds the number of stops and the control types of
unnamed stops only, never a name. ``tab_to`` presses Tab until the focused element matches.
``Dialog`` sends keys to the focused dialog without bringing the main window to the front
(``App.send``), so a walk and Escape reach a modal dialog. ``dialog`` opens a dialog with
Space or Enter on the focused control, walks it and closes it with Escape. No row presses a
key that confirms a download, an import or a removal: a dialog is only ever closed with
Escape, and **Download** stays disabled while the licence box is unticked.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from native_e2e import uia
from native_e2e.evidence.model import Check
from native_e2e.rows import ui
from native_e2e.rows.common import check
from native_e2e.uia import Node

MAX_STOPS = 120  # Settings and Language packs have more stops than ui.tab_walk's default
KEYS = {"space": "{SPACE}", "enter": "{ENTER}"}


class Dialog:
    """The ``tab_walk`` surface of an open dialog: keys go to the focused window as is."""

    def __init__(self, app: Any) -> None:
        self.app = app

    def keys(self, text: str) -> None:
        self.app.send(text)

    def focused(self) -> Node | None:
        return self.app.focused()


def walk(app: Any, name: str, max_stops: int = MAX_STOPS) -> Check:
    stops = ui.tab_walk(app, max_stops)
    unnamed = sorted({kind or "none" for kind, named in stops if not named})
    closed = len(stops) < max_stops
    detail = f"stops={len(stops)}"
    if unnamed:
        detail += f" unnamed={','.join(unnamed)}"
    if not closed:
        detail += " cycle-open"
    return check(name, bool(stops) and not unnamed and closed, detail)


def named(name: str, control_type: str | None = None) -> Callable[[Node], bool]:
    """Matches an element named ``name`` (of ``control_type``; by default not a label)."""

    def match(node: Node) -> bool:
        if node.name != name:
            return False
        if control_type is None:
            return node.control_type not in ("Text", "")
        return node.control_type == control_type

    return match


def tab_to(app: Any, match: Callable[[Node], bool], max_stops: int = MAX_STOPS) -> Node | None:
    """Press Tab until the focused element matches (at most ``max_stops`` presses)."""
    node = app.focused()
    for _ in range(max_stops):
        if node is not None and match(node):
            return node
        previous = uia.element_key(node) if node is not None else None
        app.keys("{TAB}")
        node = ui._moved_focus(app, previous)
    return node if node is not None and match(node) else None


def became(probe: Callable[[], Any], timeout_s: float | None = None) -> bool:
    try:
        ui.wait(probe, timeout_s)
    except TimeoutError:
        return False
    return True


def focused_is(app: Any, name: str) -> bool:
    node = app.focused()
    return node is not None and node.name == name


def dialog(
    app: Any,
    checks: list[Check],
    label: str,
    key: str,
    title: str | Callable[[], str | None],
    walked: bool = True,
) -> bool:
    """Press ``key`` ("space" or "enter") on the focused control; once the dialog ``title``
    (or the title ``title()`` finds) is open, walk it (``walked``) and press Escape.

    Checks: ``{key}-opens-{label}``, ``{label}-tab-stops-named``, ``escape-closes-{label}``.
    Returns whether the dialog opened."""
    find = (
        title
        if callable(title)
        else (lambda: title if app.window_nodes(title) is not None else None)
    )
    app.keys(KEYS[key])
    try:
        found = ui.wait(find)
    except TimeoutError:
        checks.append(check(f"{key}-opens-{label}", False, "timeout"))
        return False
    checks.append(check(f"{key}-opens-{label}", True))
    if walked:
        checks.append(walk(Dialog(app), f"{label}-tab-stops-named"))
    app.send("{ESC}")
    ui.waited(checks, f"escape-closes-{label}", lambda: app.window_nodes(found) is None)
    return True
