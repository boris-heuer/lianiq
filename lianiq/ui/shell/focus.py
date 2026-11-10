"""Keyboard focus order in the shell (CAP-0168 spec §2.3.1, AC-28).

Tab moves sidebar → workspace → session strip and wraps around; Shift+Tab goes back. Inside
each region the order is Qt's focus chain (creation order). The order is computed when Tab
is pressed, so controls created later (notice actions, held-turn buttons) still fall in
their region rather than at the end of Qt's chain behind the strip.
"""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget


def is_tab_stop(widget: QWidget) -> bool:
    return (
        widget.isEnabled()
        and widget.isVisible()
        and bool(widget.focusPolicy() & Qt.FocusPolicy.TabFocus)
        and widget.focusProxy() is None
    )


def focus_chain(window: QWidget) -> list[QWidget]:
    """Qt's focus chain of ``window``, once round, without the window itself."""
    chain: list[QWidget] = []
    widget = window.nextInFocusChain()
    while widget is not None and widget is not window and widget not in chain:
        chain.append(widget)
        widget = widget.nextInFocusChain()
    return chain


def tab_stops(window: QWidget, regions: Sequence[QWidget]) -> list[QWidget]:
    """The Tab stops of ``regions`` in region order, each region in focus-chain order."""
    chain = focus_chain(window)
    return [
        widget
        for region in regions
        for widget in chain
        if (widget is region or region.isAncestorOf(widget)) and is_tab_stop(widget)
    ]


def step(window: QWidget, regions: Sequence[QWidget], forward: bool) -> QWidget | None:
    """The Tab stop after (``forward``) or before the focused widget; ``None`` if none."""
    stops = tab_stops(window, regions)
    if not stops:
        return None
    current = window.focusWidget()
    offset = 1 if forward else -1
    if current in stops:
        return stops[(stops.index(current) + offset) % len(stops)]
    # Focus is on a widget that is not a Tab stop (a banner or the held-turn bar holding it):
    # continue with the next Tab stop along Qt's chain from there.
    chain = focus_chain(window)
    if current in chain:
        start = chain.index(current)
        for distance in range(1, len(chain)):
            widget = chain[(start + offset * distance) % len(chain)]
            if widget in stops:
                return widget
    return stops[0] if forward else stops[-1]
