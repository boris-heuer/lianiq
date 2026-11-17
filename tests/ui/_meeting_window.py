"""Shared helpers for the Meeting workspace tests (CAP-0177 WI-04; ``test_meeting_*.py``).

A shown ``MainWindow`` over spy adapters with the reference devices of the e2e plan (a
speakerphone with a microphone and a speaker, the laptop microphone as the Windows default,
a USB headset and the laptop speakers) and a ``FactorySpy`` as ``meeting_factory``: it
records each call and builds a real ``MeetingController`` on the synthetic capture streams
and spy engines of ``tests/meeting/support.py``, so a started meeting opens no device.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from lianiq.meeting.contracts import MeetingRole
from lianiq.meeting.controller import MeetingController, SharedEngines
from lianiq.ui.shell.workspaces import WorkspaceId
from tests._fake_devices import mic, speakers
from tests._spy_window import build_window
from tests.languages.synthetic import SpyTranslator
from tests.meeting.support import AUDIO, PcmSynthesizer, ScriptedRecognizer, SyntheticStreams
from tests.ui.test_main_window_session import click, wait_until

LAPTOP_MIC = mic("Microphone Array (Realtek Audio)", 0, "laptop-mic")
LAPTOP_SPEAKERS = speakers("Speakers (Realtek Audio)", 1, "laptop-spk")
JABRA_MIC = mic("Microphone (Jabra Speak2 75)", 2, "jabra-mic")
JABRA_SPEAKER = speakers("Speakers (Jabra Speak2 75)", 3, "jabra-spk")
HEADSET_MIC = mic("Headset Microphone (USB Headset)", 4, "headset-mic")
HEADSET = speakers("Headphones (USB Headset)", 5, "headset-spk")
DEVICES = (LAPTOP_MIC, LAPTOP_SPEAKERS, JABRA_MIC, JABRA_SPEAKER, HEADSET_MIC, HEADSET)
TABLE, SPEAKER = MeetingRole.TABLE_CAPTURE, MeetingRole.TABLE_RENDER
USER, LOCAL = MeetingRole.USER_CAPTURE, MeetingRole.LOCAL_RENDER
MEETING = WorkspaceId.MEETING


class FactorySpy:
    """``meeting_factory``: records the call, builds a controller on synthetic adapters."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.controllers: list[MeetingController] = []
        self.streams = SyntheticStreams()

    def __call__(self, session, endpoints, options, owner, publish) -> MeetingController:
        self.calls.append((session, endpoints, options))
        engines = SharedEngines(ScriptedRecognizer(), SpyTranslator(), PcmSynthesizer())
        controller = MeetingController(
            session,
            endpoints,
            options,
            engines,
            owner,
            publish,
            audio=AUDIO,
            stream_factory=self.streams,
        )
        self.controllers.append(controller)
        return controller


def build_meeting_window(tmp_path, monkeypatch, *, devices=DEVICES, **options):
    """The window with ``devices`` (the first capture is the Windows default) on Meeting."""
    window = build_window(tmp_path, monkeypatch, **options)
    window.fake_devices.set(*devices)
    assert window.device_setup.refresh()  # the full refresh lists them in Meeting too
    window.meeting_factory = FactorySpy()
    window.show_workspace(MEETING)
    return window


def end_and_wait(window) -> None:
    """End a running meeting and wait until it drained (``STOPPED`` reached the page)."""
    meeting = window.meeting
    if meeting.active():
        meeting.end_meeting()
        assert wait_until(lambda: not meeting.active())


@pytest.fixture(name="window")
def meeting_window(tmp_path, spies, monkeypatch):
    window = build_meeting_window(tmp_path, monkeypatch)
    yield window
    end_and_wait(window)
    window.stop_listening()
    window.close()


def choose(window, role: MeetingRole, endpoint=None) -> None:
    """Pick ``endpoint`` (``None``: the first item) in ``role``'s combo, as the PO does."""
    combo = window.meeting.combos[role]
    index = 0 if endpoint is None else combo.findData(endpoint.endpoint_id)
    assert index >= 0, endpoint
    combo.setCurrentIndex(index)
    combo.activated.emit(index)


def assign_table(window) -> None:
    """The speakerphone as table microphone; its speaker follows the partner suggestion."""
    choose(window, TABLE, JABRA_MIC)
    assert window.meeting.combos[SPEAKER].currentData() == JABRA_SPEAKER.endpoint_id


def start_meeting(window) -> None:
    click(window.meeting.start_button)
    assert wait_until(lambda: window.meeting.controller is not None)
    assert wait_until(lambda: window.meeting.controller.running)


def availability(window) -> str:
    return window.meeting.availability_label.text()


def notice_title(window, workspace: WorkspaceId) -> str:
    notice = window.notices.top(workspace)
    return "" if notice is None else notice.title
