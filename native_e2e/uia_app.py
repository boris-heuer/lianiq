"""The running Lianiq window as the UIA rows use it (CAP-0174 contract §5, §6).

``launch`` starts ``python -m lianiq`` from the checkout in the real window and connects
pywinauto (``backend="uia"``). ``App`` is the only surface the rows E-01, E-11, E-03 and E-10
touch: ``nodes()`` (one ``uia.snapshot``), ``press`` (a real mouse click, or focus and Space
below a scroll area's fold: a UIA Invoke on a button that opens a modal dialog would not
return until the dialog closes), ``keys``
(SendInput to the focused window), ``choose`` (expand a combo box, click an item), ``window_nodes``
(a top-level window of the app such as the export dialog), ``type_into``, ``processes``
(psutil, for the E-01 model-file check), ``popup_nodes`` and ``click`` (dialogs and popup
menus, for ``packs_import``), ``focused`` (``rows.ui.tab_walk``) and ``close``. ``launch``
starts with ``--no-setup-assistant`` unless ``setup_assistant=True`` (first-run rows: the
local settings file is deleted first); ``settings_reset`` resets it to S-03's.
E-03 keeps its app in ``ctx.state["app"]`` for E-10; ``close_open`` closes whatever is left
after the UIA rows, before the S-04 window closes.
"""

from __future__ import annotations

import shutil
import subprocess
from typing import TYPE_CHECKING, Any

from native_e2e import uia
from native_e2e.evidence.sums import file_sha256

if TYPE_CHECKING:
    from native_e2e.context import RunContext
    from native_e2e.uia import Node


class App:
    def __init__(self, process: subprocess.Popen[bytes], window: Any) -> None:
        self.process = process
        self.window = window

    @property
    def rect(self) -> tuple[int, int, int, int]:
        rect = self.window.rectangle()
        return (rect.left, rect.top, rect.right, rect.bottom)

    def pids(self) -> list[int]:
        return uia.app_pids(self.process.pid)

    def processes(self) -> list[Any]:
        import psutil

        found = []
        for pid in self.pids():
            try:
                found.append(psutil.Process(pid))
            except psutil.Error:
                continue
        return found

    def nodes(self) -> list[Node]:
        return uia.snapshot(self.window)

    def press(self, node: Node) -> None:
        """Click ``node``; one outside the window (below a scroll area's fold) gets Space.

        Qt reports such an element visible and on screen, so a click would land outside the
        window: it is focused through UIA and activated with the keyboard instead.
        """
        self.window.set_focus()
        if self.within(node):
            node.handle.click_input()
        else:
            node.handle.set_focus()
            uia.send_keys("{SPACE}")

    def within(self, node: Node) -> bool:
        """Whether the centre of ``node`` lies inside the window."""
        left, top, right, bottom = self.rect
        x = (node.rect[0] + node.rect[2]) / 2
        y = (node.rect[1] + node.rect[3]) / 2
        return left <= x < right and top <= y < bottom

    def keys(self, text: str) -> None:
        self.window.set_focus()
        uia.send_keys(text)

    def choose(self, node: Node, item: str) -> None:
        """Select the item whose text is ``item`` in the combo box ``node``.

        Qt lists a combo box's items only while it is expanded, and a UIA Select or Invoke on
        a listed item does not commit it; a real click does. ``TimeoutError`` when the item
        is not listed (the combo box is collapsed again).
        """
        self.window.set_focus()
        node.handle.expand()
        found: list[Any] = []

        def listed() -> bool:
            try:
                entries = node.handle.descendants(control_type="ListItem")
                found[:] = [entry for entry in entries if entry.element_info.name == item]
            except Exception:  # noqa: BLE001 - the popup is still opening: poll again
                found.clear()
            return bool(found)

        try:
            uia.wait_for(listed, uia.UIA_TIMEOUT_S)
        except TimeoutError:
            try:
                node.handle.collapse()
            except Exception:  # noqa: BLE001, S110 - already collapsed: the timeout decides
                pass
            raise
        found[0].click_input()

    def _top_windows(self) -> list[Any]:
        from pywinauto import Desktop

        pids = set(self.pids())
        found = [w for w in Desktop(backend="uia").windows() if w.process_id() in pids]
        found += [w for w in self.window.children() if w.element_info.control_type == "Window"]
        return found

    def popup_nodes(self) -> list[Node]:
        """The nodes of every top-level window of the app (dialogs, popup menus)."""
        found: list[Node] = []
        for window in self._top_windows():
            try:
                found += uia.snapshot(window)
            except Exception:  # noqa: BLE001, S112 - closed while read
                continue
        return found

    def click(self, node: Node) -> None:
        """A real click on ``node`` without focusing the main window first (a popup menu
        closes when the main window is activated)."""
        node.handle.click_input()

    def focused(self) -> Node | None:
        return uia.focused()

    def window_nodes(self, title: str) -> list[Node] | None:
        """The nodes of the app's window named ``title`` (for example a dialog), else ``None``."""
        for window in self._top_windows():
            if window.element_info.name == title:
                return uia.snapshot(window)
        return None

    def type_into(self, node: Node, text: str, enter: bool = True) -> None:
        """Replace the field's text by typing ``text``, then press Enter (unless ``enter``
        is false: in the native folder picker Enter navigates into the folder)."""
        node.handle.set_focus()
        uia.send_keys("^a" + uia.escape_keys(text) + ("{ENTER}" if enter else ""))

    def close(self) -> int | None:
        return uia.close_app(self.process, self.window)


def settings_reset(ctx: RunContext) -> bool:
    """Put ``config/settings.local.json`` back to the S-03 backup (or delete it when none
    existed), so a settings-changing row group leaves the next one the baseline; false
    without an S-03 record (nothing is changed) or when the result does not match."""
    record = ctx.state.get("settings_backup")
    if record is None:
        return False
    target = ctx.local_settings
    if record["existed"]:
        shutil.copy2(record["path"], target)
        return target.is_file() and file_sha256(target) == record["sha256"]
    target.unlink(missing_ok=True)
    return not target.exists()


def launch(ctx: RunContext, setup_assistant: bool = False) -> App:
    """Start the app (by default with ``--no-setup-assistant``) and connect to its window.

    The assistant opens only without ``config/settings.local.json`` (``lianiq.app
    .load_settings``), so a first-run launch deletes that file first; it needs the S-03
    backup (``RuntimeError`` otherwise), which T-01 and ``settings_reset`` use.
    """
    if setup_assistant:
        if ctx.state.get("settings_backup") is None:
            raise RuntimeError("first-run launch needs the S-03 settings backup")
        ctx.local_settings.unlink(missing_ok=True)
    process = uia.launch_app(ctx.python, ctx.repo, setup_assistant=setup_assistant)
    try:
        window = uia.connect(process)
    except Exception:
        uia.close_app(process)
        raise
    try:
        window.set_focus()  # in front of anything open at sign-in, such as the Start menu
    except Exception:  # noqa: BLE001, S110 - every press and key focuses the window again
        pass
    return App(process, window)


def close_open(ctx: RunContext) -> None:
    """Close the app a UIA row left open (E-03 → E-10), if any."""
    app = ctx.state.pop("app", None)
    if app is not None:
        app.close()
