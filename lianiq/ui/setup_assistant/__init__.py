"""The first-run setup assistant (CAP-0171 WI-06, spec §2.2.1).

``lianiq.app.main`` opens it when the first run is due (C §9) and the Language packs header
reopens it with **Run setup assistant**; ``MainWindow`` itself never opens it (AC-32).
"""

from __future__ import annotations

from lianiq.ui.setup_assistant.assistant import SetupAssistant


def open_setup_assistant(host) -> SetupAssistant:
    """Show the assistant over ``host`` (non-modal); an open one is raised, not duplicated."""
    current = getattr(host, "setup_assistant", None)
    if current is None:
        current = SetupAssistant(host)
        host.setup_assistant = current

        def closed(_result: int) -> None:
            host.setup_assistant = None
            current.deleteLater()

        current.finished.connect(closed)
    current.show()
    current.raise_()
    current.activateWindow()
    return current


__all__ = ["SetupAssistant", "open_setup_assistant"]
