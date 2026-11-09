"""Shared helpers for the shell notice tests (CAP-0168 WI-03; ``test_shell_notices*.py``).

The offscreen ``window`` fixture over spy adapters, the fake device inventory and readers
for the workspace notice banner.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from lianiq.audio.devices import AudioDevice
from lianiq.ui.shell.workspaces import WorkspaceId
from tests._spy_window import build_window
from tests.ui._language_helpers import start, submit, transcript, wait_until

CONVERSATION = WorkspaceId.CONVERSATION
MICROPHONE = AudioDevice(0, "Test microphone", 1, 0)
SPEAKERS = AudioDevice(1, "Test speakers", 0, 2)
PAIR_SOURCE = "Conversation · German ↔ Mandarin (Simplified)"


# The explicit name keeps the fixture "window" for test modules importing this function.
# It requests ``spies``, which the test module imports from ``tests/_spy_window.py``.
@pytest.fixture(name="window")
def notice_window(tmp_path, spies, monkeypatch):
    window = build_window(tmp_path, monkeypatch)
    window.activateWindow()
    yield window
    window.stop_listening()
    window.close()


def plug(monkeypatch, *devices) -> None:
    """The fake device inventory the next enumeration (Reconnect) reads."""
    import lianiq.ui.workspaces.conversation as conversation_module

    monkeypatch.setattr(conversation_module, "list_audio_devices", lambda: list(devices))


def banner(window, workspace=CONVERSATION):
    return window.banners[workspace]


def shown(window, workspace=CONVERSATION):
    """(title, detail, action labels) of the visible banner."""
    item = banner(window, workspace)
    assert item.isVisible()
    labels = [button.accessibleName() for button in item.action_buttons]
    return item.title_label.text(), item.detail_label.text(), labels


def action(window, label: str, workspace=CONVERSATION):
    return next(b for b in banner(window, workspace).action_buttons if b.accessibleName() == label)


def one_turn(window, spies) -> None:
    start(window)
    submit(window, spies, transcript("Guten Tag", "de"))
    assert wait_until(lambda: len(window.history) == 1)
