"""F8 and F9 of the shell (session-status-truthfulness spec §2.2.1, AC-01..AC-03).

**F8** runs the start action of the page that is shown, the same callable as that page's
Start button, so every guard of the button (busy owner, devices, readiness, running)
applies: Conversation → ``ConversationWorkspace.start_listening``, Listen & translate →
``ListenWorkspace.start``, Meeting → ``start_meeting``, Call Bridge → ``start_call_bridge``.
On every other page F8 starts nothing and the status bar shows ``F8_NO_SESSION_PAGE``.

**F9** only calls ``ActiveSessionOwner.stop()``: while idle it changes nothing visible.

``install_shortcuts`` binds F8, F9 and Ctrl+1…Ctrl+7 and runs the diagnostic start
arguments (``--diagnostic-wav``, ``--diagnostic-auto-start``), which start Conversation
through ``MainWindow.start_listening`` (moved out of ``main_window`` for its size limit).
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QKeySequence, QShortcut

from lianiq.ui.shell.workspaces import DEFAULT_ENTRIES, WorkspaceId
from lianiq.ui.strings_session import F8_HINT_MS, F8_NO_SESSION_PAGE

# The page's Start callable, looked up when F8 is pressed (spies and rebinding see it).
STARTERS: dict[WorkspaceId, Callable[[object], Callable[[], None]]] = {
    WorkspaceId.CONVERSATION: lambda window: window.conversation.start_listening,
    WorkspaceId.LISTEN: lambda window: window.listen.start,
    WorkspaceId.MEETING: lambda window: window.meeting.start_meeting,
    WorkspaceId.CALL_BRIDGE: lambda window: window.call_bridge.start_call_bridge,
}


def start_current_page(window) -> None:
    """**F8**: start the shown page's mode, or show the hint on a page without a session."""
    starter = STARTERS.get(window.current_workspace())
    if starter is None:
        window.statusBar().showMessage(F8_NO_SESSION_PAGE, F8_HINT_MS)
        return
    starter(window)()


def stop_active_session(window) -> None:
    """**F9** / the strip's **Stop**: the owner stops the active mode; idle, nothing happens."""
    window.session_owner.stop()


def install_shortcuts(window) -> None:
    """Bind F8, F9 and Ctrl+1…Ctrl+7 on ``window`` and run the diagnostic start arguments."""
    if "--diagnostic-wav" in sys.argv:
        argument_index = sys.argv.index("--diagnostic-wav") + 1
        if argument_index >= len(sys.argv):
            QTimer.singleShot(
                0, lambda: window.show_error("--diagnostic-wav requires a WAV file path")
            )
        else:
            window.conversation.diagnostic_wav = Path(sys.argv[argument_index])
            QTimer.singleShot(0, window.start_listening)
    elif "--diagnostic-auto-start" in sys.argv:
        QTimer.singleShot(0, window.start_listening)

    QShortcut(QKeySequence("F8"), window, activated=window.start_current_page)
    # F9 always targets the active session, whichever workspace is shown.
    QShortcut(QKeySequence("F9"), window, activated=window.stop_active_session)
    for index in range(len(DEFAULT_ENTRIES)):
        QShortcut(
            QKeySequence(f"Ctrl+{index + 1}"),
            window,
            activated=lambda index=index: window.navigation.select_index(index),
        )
