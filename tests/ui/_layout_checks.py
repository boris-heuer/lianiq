"""Layout checks for the size × scale matrix and the long-label tests (CAP-0168 WI-05).

Used in-process (``test_layout_matrix.py``, ``test_presentation_labels.py``) and by the
``_layout_probe`` subprocess that runs under each ``QT_SCALE_FACTOR``.
"""

from __future__ import annotations

from pathlib import Path

from lianiq.ui.shell.workspaces import DEFAULT_ENTRIES, WorkspaceId

FONTS = Path(r"C:\Windows\Fonts")
UI_FONTS = ("segoeui.ttf", "segoeuib.ttf", "msyh.ttc")
SHOWN = (WorkspaceId.CONVERSATION, WorkspaceId.CALL_BRIDGE, WorkspaceId.SETTINGS)
NAMES = [item.label for item in DEFAULT_ENTRIES]


def load_ui_fonts() -> None:
    """Register Segoe UI and Microsoft YaHei UI for the offscreen platform (no font database)."""
    from PySide6.QtGui import QFontDatabase
    from PySide6.QtWidgets import QApplication

    if QApplication.platformName() != "offscreen":
        return
    for name in UI_FONTS:
        if (FONTS / name).is_file():
            QFontDatabase.addApplicationFont(str(FONTS / name))


def settle(window, width: int, height: int) -> None:
    from PySide6.QtTest import QTest

    window.resize(width, height)
    QTest.qWait(40)


def _container(widget, window):
    """The scroll content ``widget`` lives in (scrolling allowed), else the window."""
    from lianiq.ui.shell.scroll import scroll_area_of

    area = scroll_area_of(widget)
    return area.widget() if area is not None else window


def elided(window) -> list[str]:
    """Shown buttons and labels whose text does not fit, or that lie outside their container.

    The held-turn excerpt is excluded: it is elided by design, full text in the tooltip (AC-11).
    """
    from PySide6.QtCore import QPoint, QRect
    from PySide6.QtWidgets import QAbstractButton, QLabel

    found = []
    widgets = [*window.findChildren(QAbstractButton), *window.findChildren(QLabel)]
    for widget in widgets:
        if not widget.isVisible() or widget is window.held_turn_bar.transcript_label:
            continue
        name = widget.text().replace("\n", " ") or widget.accessibleName() or widget.objectName()
        if isinstance(widget, QLabel) and widget.wordWrap():
            short = widget.height() < widget.heightForWidth(widget.width())
        else:
            hint = widget.sizeHint()
            short = widget.width() < hint.width() or widget.height() < hint.height()
        container = _container(widget, window)
        rect = QRect(widget.mapTo(container, QPoint(0, 0)), widget.size())
        outside = not container.rect().contains(rect)
        if short or outside:
            found.append(f"{name!r}: {widget.width()}x{widget.height()} hint {widget.sizeHint()}")
    return found


def in_view(widget, window) -> bool:
    """``widget`` is shown inside the window and not inside a scroll area."""
    from PySide6.QtCore import QPoint, QRect

    from lianiq.ui.shell.scroll import scroll_area_of

    if not widget.isVisible() or scroll_area_of(widget) is not None:
        return False
    rect = QRect(widget.mapTo(window, QPoint(0, 0)), widget.size())
    return window.rect().contains(rect)


def actions_of(window, workspace: WorkspaceId) -> list:
    """The Start/Stop controls of ``workspace``; the strip's **Stop (F9)** comes last."""
    if workspace is WorkspaceId.CALL_BRIDGE:
        panel = window.call_bridge_panel
        return [panel.start_button, panel.stop_button, window.stop_button]
    if workspace is WorkspaceId.SETTINGS:
        return [window.stop_button]
    return [window.start_button, window.stop_button]


def matrix_problems(window, width: int, height: int) -> list[str]:
    """Every AC-29 rule at one size, idle and with a running session, in each workspace."""
    from tests.ui._language_helpers import start

    problems = []
    for running in (False, True):
        if running:
            start(window)
        settle(window, width, height)
        if (window.width(), window.height()) != (width, height):
            problems.append(f"window is {window.width()}x{window.height()}")
        for workspace in SHOWN:
            window.show_workspace(workspace)
            settle(window, width, height)
            where = f"{width}x{height} {workspace.value} running={running}"
            controls = actions_of(window, workspace)
            if not running:
                controls = controls[:-1]  # the strip and its Stop show only while running
            problems += [
                f"{where}: {c.text()!r} not in view" for c in controls if not in_view(c, window)
            ]
            problems += [f"{where}: {text}" for text in elided(window)]
        compact = window.navigation.compact
        if compact != (width < 1000):
            problems.append(f"{width}x{height}: icon rail is {compact}")
        names = [window.navigation.buttons[item.id].accessibleName() for item in DEFAULT_ENTRIES]
        if names != NAMES:
            problems.append(f"{width}x{height}: accessible names {names}")
        window.show_workspace(WorkspaceId.CONVERSATION)
    window.stop_listening()
    return problems
