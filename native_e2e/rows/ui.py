"""Shared steps of the UIA rows E-01, E-11, E-03, E-10 and E-13 (CAP-0174 contract §5).

``tab_walk`` is the keyboard walk of the accessibility rows (spec §2.1.7).

Every wait polls a state with ``uia.wait_for`` (default 20 s, model readiness 300 s); no row
sleeps for a fixed time. The visible texts come from ``lianiq.ui.strings`` of the checked-out
commit, imported when a row runs, so a renamed text fails that row only. ``screenshot`` writes
a masked PNG through ``screens.capture`` (endpoint names, device combos, the transcript
panels and every element showing a transcript needle of ``ctx.state["transcripts"]``).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from typing import Any

from native_e2e import audio, screens, uia
from native_e2e.evidence.model import Artifact, Check
from native_e2e.rows.common import check
from native_e2e.uia import Node

TIMEOUT_S = uia.UIA_TIMEOUT_S
MODEL_TIMEOUT_S = uia.MODEL_TIMEOUT_S
POLL_S = 0.25
_LABEL = re.compile(r"^[^:\n]{1,40}:\s+(.+)$")  # "German: <text>" → "<text>"
MIN_NEEDLE = 4  # shorter transcript lines are not useful needles
# Qt exposes the checkable sidebar QToolButtons as UIA CheckBox, not Button (native run
# 44267851808 found "0 entries"); Button stays accepted for a plain push button.
NAV_CONTROL_TYPES = ("CheckBox", "Button")


def strings() -> Any:
    from lianiq.ui import strings as texts

    return texts


def wait[T](probe: Callable[[], T | None], timeout_s: float | None = None) -> T:
    """The first truthy ``probe()`` result; ``TimeoutError`` after the timeout."""
    found: list[T] = []

    def ready() -> bool:
        value = probe()
        if value:
            found.append(value)
        return bool(value)

    uia.wait_for(ready, TIMEOUT_S if timeout_s is None else timeout_s, POLL_S)
    return found[-1]


def wait_nodes[T](app: Any, pick: Callable[[list[Node]], T | None], timeout_s=None) -> T:
    return wait(lambda: pick(app.nodes()), timeout_s)


def waited(checks: list[Check], name: str, probe: Callable[[], Any], timeout_s=None) -> bool:
    """Append ``name`` as passed when ``probe`` becomes true in time, else as a timeout."""
    try:
        wait(probe, timeout_s)
    except TimeoutError:
        checks.append(check(name, False, "timeout"))
        return False
    checks.append(check(name, True))
    return True


def find(nodes: Iterable[Node], name: str, control_type: str | None = None) -> Node | None:
    """The first shown element named ``name`` (of ``control_type``)."""
    return next(
        (
            node
            for node in nodes
            if node.visible
            and node.name == name
            and (control_type is None or node.control_type == control_type)
        ),
        None,
    )


def shows(nodes: Iterable[Node], text: str) -> bool:
    """Whether a shown element is named ``text`` or carries it as its help text."""
    return any(node.visible and text in (node.name, node.description) for node in nodes)


def sidebar(nodes: Iterable[Node], region: str) -> list[Node]:
    """The shown entry buttons of the navigation region, in tree order."""
    return [
        node
        for node in nodes
        if node.visible and node.control_type in NAV_CONTROL_TYPES and region in node.parents
    ]


def select(app: Any, label: str, region: str) -> bool:
    """Click the sidebar entry ``label`` and wait until it is the selected one."""
    entry = next((node for node in sidebar(app.nodes(), region) if node.name == label), None)
    if entry is None:
        return False
    app.press(entry)

    def selected(nodes: list[Node]) -> bool:
        return any(node.name == label and node.selected for node in sidebar(nodes, region))

    try:
        wait_nodes(app, selected)
    except TimeoutError:
        return False
    return True


def transcript_needles(transcripts: Iterable[str]) -> list[str]:
    """Each transcript line, also without its language label, at least four characters."""
    needles: list[str] = []
    for text in transcripts:
        for line in (text or "").splitlines():
            line = line.strip()
            match = _LABEL.match(line)
            for needle in (line, match.group(1).strip() if match else ""):
                if len(needle) >= MIN_NEEDLE and needle not in needles:
                    needles.append(needle)
    return needles


def screenshot(ctx: Any, app: Any, relative: str, name: str) -> tuple[Check, Artifact]:
    """A masked screenshot of the window; the check records how many regions were masked."""
    texts = strings()
    combos = (texts.NOTICE_MICROPHONE, texts.NOTICE_SPEAKERS)
    needles = transcript_needles(ctx.state.get("transcripts", []))
    names = [*audio.endpoint_names(), *needles]
    artifact, masked = screens.capture(ctx, app, relative, names, combos)
    return check(name, True, f"masked={masked}"), artifact


FOCUS_MOVE_S = 2.0  # how long a Tab may take to move the focus


def _moved_focus(app: Any, previous: tuple | None) -> Node | None:
    """The focused element once it differs from ``previous`` (or after the move timeout)."""
    found: list[Node | None] = [None]

    def moved() -> bool:
        found[0] = app.focused()
        return found[0] is not None and uia.element_key(found[0]) != previous

    try:
        uia.wait_for(moved, FOCUS_MOVE_S, POLL_S)
    except TimeoutError:
        pass  # a one-stop cycle, or no focus: the last read decides
    return found[0]


def tab_walk(app: Any, max_stops: int = 60) -> list[tuple[str, bool]]:
    """Press Tab until the first focused element repeats (at most ``max_stops`` presses).

    Returns (control type, has a non-empty name) per stop, in order; never a name, so a
    device or a field value cannot reach the evidence. ``max_stops`` entries mean the
    focus cycle did not close.
    """
    stops: list[tuple[str, bool]] = []
    first: tuple | None = None
    previous: tuple | None = None
    for _ in range(max_stops):
        app.keys("{TAB}")
        node = _moved_focus(app, previous)
        if node is None:
            stops.append(("", False))
            continue
        key = uia.element_key(node)
        if key == first:
            break
        first = key if first is None else first
        previous = key
        stops.append((node.control_type, bool(node.name.strip())))
    return stops
