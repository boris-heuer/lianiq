"""The offscreen ``MainWindow`` on the Listen page over spy adapters (CAP-0170 WI-03).

``ListenWorkspace._capture`` is replaced by the WI-02 ``FakeCapture``, so a test speaks
segments from a worker thread; the spy recogniser returns the scripted transcripts.
"""

from __future__ import annotations

from lianiq.listen.lifecycle import ListenPhase
from lianiq.ui.shell.workspaces import WorkspaceId
from lianiq.ui.workspaces.listen import ListenWorkspace
from tests._spy_window import build_window
from tests.languages.synthetic import SyntheticTranscript
from tests.listen._listen_helpers import FakeCapture
from tests.ui._language_packs_helpers import wait_until


def listen_window(tmp_path, monkeypatch, **options):
    captures: list[FakeCapture] = []

    def capture(self, on_utterance, on_error) -> FakeCapture:
        captures.append(FakeCapture(on_utterance, on_error))
        return captures[-1]

    monkeypatch.setattr(ListenWorkspace, "_capture", capture)
    window = build_window(tmp_path, monkeypatch, **options)
    window.listen_captures = captures
    assert window.show_workspace(WorkspaceId.LISTEN)
    return window


def phase_is(window, phase: ListenPhase) -> bool:
    return wait_until(lambda: window.listen.controller.phase is phase)


def start(window) -> None:
    window.start_current_page()  # F8 on the Listen page
    assert phase_is(window, ListenPhase.LISTENING)


def speak(window, spies, *texts: str) -> None:
    """One segment per text, recognised as German."""
    for text in texts:
        spies.recognizer.results.append(SyntheticTranscript(text, "de", 0.99, 1.0))
        window.listen_captures[-1].speak()


def states(window) -> list:
    return [row.state for row in window.listen.controller.transcript.rows]
