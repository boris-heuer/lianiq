"""UI Automation base helpers for the native rows (CAP-0174 contract §1, §5, §6).

``wait_for`` is the only way a row waits: it polls a state with a timeout and never sleeps
for a fixed time to let the app "settle". The other helpers start and close the real app
(``python -m lianiq`` with ``QT_QPA_PLATFORM`` unset), connect pywinauto with
``backend="uia"``, send keys with SendInput and read elements. pywinauto is imported lazily:
it is installed only in the VM image (``native_e2e/requirements-native-lock.txt``), so this
module stays importable in normal CI. The UIA rows E-01, E-11, E-03 and E-10 (WI-04) build on
these helpers.
"""

from __future__ import annotations

import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from native_e2e.proc import child_env

UIA_TIMEOUT_S = 20.0
MODEL_TIMEOUT_S = 120.0


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
    """Start ``python -m lianiq`` from the checkout in the signed-in session."""
    return subprocess.Popen(
        [python, "-m", "lianiq"],
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


def _try_connect(application: Any, pid: int) -> bool:
    try:
        application.connect(process=pid, timeout=0)
        return bool(application.windows())
    except Exception:  # noqa: BLE001 - pywinauto raises several types until the window exists
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
