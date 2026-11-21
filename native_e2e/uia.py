"""UI Automation base helpers for the native rows (CAP-0174 contract §1, §5, §6).

``wait_for`` is the only way a row waits: it polls a state with a timeout and never sleeps
for a fixed time to let the app "settle". The other helpers start and close the real app
(``python -m lianiq`` with ``QT_QPA_PLATFORM`` unset), connect pywinauto with
``backend="uia"``, send keys with SendInput and read elements. pywinauto and psutil are
imported lazily: they are installed only in the VM image
(``native_e2e/requirements-native-lock.txt``), so this module stays importable in normal CI.

``snapshot`` reads the window tree once into plain ``Node`` values (name, control type,
state, help text, value, rectangle, ancestor names), so the UIA rows E-01, E-11, E-03 and
E-10 decide on data that tests can fake. The venv launcher starts the base interpreter as a
child process (spec §9 item 2), so the window may belong to a child of the started process.
"""

from __future__ import annotations

import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from native_e2e.proc import child_env

UIA_TIMEOUT_S = 20.0
MODEL_TIMEOUT_S = 300.0


def wait_for(predicate: Callable[[], bool], timeout_s: float, poll_s: float = 0.25) -> None:
    """Return once ``predicate()`` is true; raise ``TimeoutError`` after ``timeout_s``."""
    deadline = time.monotonic() + timeout_s
    while True:
        if predicate():
            return
        if time.monotonic() >= deadline:
            raise TimeoutError(f"state not reached within {timeout_s:g} s")
        time.sleep(poll_s)


def launch_app(python: str, repo: Path) -> subprocess.Popen[bytes]:
    """Start ``python -m lianiq`` in the signed-in session, without the setup assistant."""
    return subprocess.Popen(
        [python, "-m", "lianiq", "--no-setup-assistant"],
        cwd=repo,
        env=child_env(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def connect(process: subprocess.Popen[bytes], timeout_s: float = UIA_TIMEOUT_S) -> Any:
    """Return the app's top-level UIA window once it is visible."""
    from pywinauto import Application

    application = Application(backend="uia")
    wait_for(lambda: _try_connect(application, process.pid), timeout_s)
    window = application.top_window()
    wait_for(lambda: window.is_visible(), timeout_s)
    return window


def app_pids(pid: int) -> list[int]:
    """``pid`` and every child of it (the venv launcher and the interpreter it started)."""
    import psutil

    try:
        return [pid, *(child.pid for child in psutil.Process(pid).children(recursive=True))]
    except psutil.Error:
        return [pid]


def _try_connect(application: Any, pid: int) -> bool:
    for candidate in app_pids(pid):
        try:
            application.connect(process=candidate, timeout=0)
            if application.windows():
                return True
        except Exception:  # noqa: BLE001, S112 - pywinauto raises several types until then
            continue
    return False


def close_app(
    process: subprocess.Popen[bytes], window: Any = None, timeout_s: float = UIA_TIMEOUT_S
) -> int | None:
    """Close the window (or terminate), wait for the exit and return the exit code."""
    if window is not None:
        try:
            window.close()
        except Exception:  # noqa: BLE001, S110 - already gone: the exit wait decides
            pass
    try:
        wait_for(lambda: process.poll() is not None, timeout_s)
    except TimeoutError:
        process.kill()
        process.wait(timeout=timeout_s)
    return process.returncode


def send_keys(keys: str) -> None:
    """Send ``keys`` (pywinauto notation, for example ``"{F8}"``) with SendInput."""
    from pywinauto.keyboard import send_keys as _send

    _send(keys, with_spaces=True)


_KEY_SPECIALS = set("+^%~(){}[]")


def escape_keys(text: str) -> str:
    """``text`` for ``send_keys`` so every character is typed literally."""
    return "".join(f"{{{char}}}" if char in _KEY_SPECIALS else char for char in text)


@dataclass(frozen=True)
class Node:
    """One UIA element as read once: what the rows decide on (rect: left, top, right, bottom)."""

    name: str
    control_type: str
    enabled: bool = True
    visible: bool = True
    selected: bool | None = None
    description: str = ""
    value: str | None = None
    rect: tuple[int, int, int, int] = (0, 0, 0, 0)
    automation_id: str = ""
    parents: tuple[str, ...] = ()
    scroll: float | None = None
    handle: Any = field(default=None, compare=False, repr=False)

    def texts(self) -> tuple[str, ...]:
        return tuple(text for text in (self.name, self.description, self.value) if text)


_FULL_DESCRIPTION = 30159  # UIA_FullDescriptionPropertyId: Qt's accessible description


def _quiet(read: Callable[[], Any]) -> Any:
    try:
        return read()
    except Exception:  # noqa: BLE001 - the element has no such pattern or property
        return None


def read_node(element: Any, parents: tuple[str, ...] = ()) -> Node:
    """Read one pywinauto UIA wrapper into a ``Node`` (missing patterns read as ``None``)."""
    info = element.element_info
    raw = info.element
    toggle = _quiet(lambda: element.iface_toggle.CurrentToggleState)
    selected = bool(toggle) if toggle is not None else None
    if selected is None:
        selected = _quiet(lambda: bool(element.iface_selection_item.CurrentIsSelected))
    description = next(
        (
            str(text)
            for text in (
                _quiet(lambda: raw.CurrentHelpText),
                _quiet(lambda: raw.GetCurrentPropertyValue(_FULL_DESCRIPTION)),
            )
            if text
        ),
        "",
    )
    value = _quiet(lambda: element.iface_value.CurrentValue)
    if value is None and info.control_type == "ComboBox":
        value = _quiet(element.selected_text)  # no Value pattern: the selected item's text
    scroll = _quiet(lambda: float(element.iface_scroll.CurrentVerticalScrollPercent))
    if scroll is None and info.control_type == "ScrollBar":
        rng = _quiet(lambda: element.iface_range_value)
        if rng is not None and rng.CurrentMaximum:
            scroll = float(rng.CurrentValue) / float(rng.CurrentMaximum)
    rect = info.rectangle
    return Node(
        name=info.name or "",
        control_type=info.control_type or "",
        enabled=bool(info.enabled),
        visible=bool(info.visible),
        selected=selected,
        description=description,
        value=str(value) if value is not None else None,
        rect=(rect.left, rect.top, rect.right, rect.bottom),
        automation_id=str(info.automation_id or ""),
        parents=parents,
        scroll=scroll,
        handle=element,
    )


def snapshot(root: Any) -> list[Node]:
    """Every descendant of ``root`` in tree order, with the names of its ancestors."""
    nodes: list[Node] = []

    def walk(element: Any, parents: tuple[str, ...]) -> None:
        for child in _quiet(element.children) or ():
            try:
                node = read_node(child, parents)
            except Exception:  # noqa: BLE001, S112 - gone while read (a closing dialog)
                continue
            nodes.append(node)
            walk(child, (*parents, node.name))

    walk(root, (root.element_info.name or "",))
    return nodes


def elements(window: Any, control_type: str) -> list[Any]:
    """All descendants of ``window`` of one UIA control type, in tree order."""
    return list(window.descendants(control_type=control_type))


def element_state(element: Any) -> dict[str, object]:
    """Name, enabled and selected state and help text of one UIA element."""
    info = element.element_info
    selected: bool | None
    try:
        selected = bool(element.is_selected())
    except Exception:  # noqa: BLE001 - the element has no selection pattern
        selected = None
    return {
        "name": info.name,
        "enabled": bool(info.enabled),
        "selected": selected,
        "description": getattr(info, "help_text", None) or None,
    }
