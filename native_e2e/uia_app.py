"""The running Lianiq window as the UIA rows use it (CAP-0174 contract §5, §6).

``launch`` starts ``python -m lianiq`` from the checkout in the real window and connects
pywinauto (``backend="uia"``). ``App`` is the only surface the rows E-01, E-11, E-03 and E-10
touch: ``nodes()`` (one ``uia.snapshot``), ``press`` (a real mouse click: a UIA Invoke on a
button that opens a modal dialog would not return until the dialog closes), ``keys``
(SendInput to the focused window), ``choose`` (an item of a combo box), ``window_nodes``
(a top-level window of the app such as the export dialog), ``type_into``, ``processes``
(psutil, for the E-01 model-file check) and ``close``. E-03 keeps its app in ``ctx.state["app"]`` for E-10; ``close_open`` closes whatever
is left after the UIA rows, before the S-04 window closes.
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING, Any

from native_e2e import uia

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
        self.window.set_focus()
        node.handle.click_input()

    def keys(self, text: str) -> None:
        self.window.set_focus()
        uia.send_keys(text)

    def choose(self, node: Node, item: str) -> None:
        """Select the item whose text is ``item`` in the combo box ``node``."""
        self.window.set_focus()
        node.handle.select(item)

    def _top_windows(self) -> list[Any]:
        from pywinauto import Desktop

        pids = set(self.pids())
        found = [w for w in Desktop(backend="uia").windows() if w.process_id() in pids]
        found += [w for w in self.window.children() if w.element_info.control_type == "Window"]
        return found

    def window_nodes(self, title: str) -> list[Node] | None:
        """The nodes of the app's window named ``title`` (for example a dialog), else ``None``."""
        for window in self._top_windows():
            if window.element_info.name == title:
                return uia.snapshot(window)
        return None

    def type_into(self, node: Node, text: str) -> None:
        """Replace the field's text by typing ``text``, then press Enter."""
        node.handle.set_focus()
        uia.send_keys("^a" + uia.escape_keys(text) + "{ENTER}")

    def close(self) -> int | None:
        return uia.close_app(self.process, self.window)


def launch(ctx: RunContext) -> App:
    process = uia.launch_app(ctx.python, ctx.repo)
    try:
        window = uia.connect(process)
    except Exception:
        uia.close_app(process)
        raise
    return App(process, window)


def close_open(ctx: RunContext) -> None:
    """Close the app a UIA row left open (E-03 → E-10), if any."""
    app = ctx.state.pop("app", None)
    if app is not None:
        app.close()
