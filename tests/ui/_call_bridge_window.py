"""Shared helpers for the MainWindow Call Bridge tests (CAP-0169 WI-05, AC-09).

Fake endpoint streams, the Call Bridge window builder, endpoint assignment and the
offscreen ``window`` fixture over spy adapters; used by ``test_main_window_call_bridge*.py``
and the shell tests that drive a Call Bridge session.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import ClassVar

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from lianiq.call_bridge.contracts import EndpointRole
from lianiq.domain import AudioUtterance
from tests._spy_window import config_without_stt_and_voices, provision_stt_and_voices
from tests.call_bridge.support import DE, mapping

AUDIO = AudioUtterance(np.zeros(1_600, dtype=np.float32), 16_000)


def bridge_notice(window) -> str:
    """The title of the Call Bridge workspace's top notice (CAP-0168 WI-03)."""
    from lianiq.ui.shell.workspaces import WorkspaceId

    notice = window.notices.top(WorkspaceId.CALL_BRIDGE)
    return "" if notice is None else notice.title


def wait_until(condition, timeout_ms: int = 3_000) -> bool:
    from PySide6.QtTest import QTest

    waited = 0
    while not condition() and waited < timeout_ms:
        QTest.qWait(10)
        waited += 10
    return condition()


def click(widget) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    QTest.mouseClick(widget, Qt.MouseButton.LeftButton)


class FakeCaptureStream:
    instances: ClassVar[list[FakeCaptureStream]] = []

    def __init__(self, endpoint, _config, on_utterance, on_level=None, on_error=None) -> None:
        self.endpoint = endpoint
        self.on_utterance = on_utterance
        self.running = False
        FakeCaptureStream.instances.append(self)

    def start(self) -> None:
        self.running = True

    def stop(self) -> None:
        self.running = False

    def rebind(self, endpoint) -> None:
        self.endpoint = endpoint


class FakePlaybackStream:
    played: ClassVar[list[tuple[str, str]]] = []

    def __init__(self, endpoint) -> None:
        self.endpoint = endpoint

    def play(self, path) -> None:
        FakePlaybackStream.played.append((self.endpoint.endpoint_id, Path(path).name))

    def rebind(self, endpoint) -> None:
        self.endpoint = endpoint


def build_call_bridge_window(
    tmp_path, monkeypatch, *, local_language: str = DE, registry=None, configure=None
):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    import lianiq.ui.main_window as main_window_module
    import lianiq.ui.workspaces.call_bridge as call_bridge_module
    import lianiq.ui.workspaces.conversation as conversation_module
    from lianiq.app import build_pipeline
    from lianiq.audio.endpoints import EndpointInventory
    from lianiq.languages import BUILTIN_REGISTRY, ReadinessProbe

    QApplication.instance() or QApplication([])
    inventory = EndpointInventory(mapping().values())
    # One microphone and one speaker, as in build_window(), so conversation modes are ready.
    from tests._fake_devices import MICROPHONE, SPEAKERS, FakeDevices

    FakeDevices(MICROPHONE, SPEAKERS).install(monkeypatch)
    monkeypatch.setattr(call_bridge_module, "list_audio_endpoints", lambda: inventory)
    monkeypatch.setattr(call_bridge_module, "EndpointCaptureStream", FakeCaptureStream)
    monkeypatch.setattr(call_bridge_module, "EndpointPlaybackStream", FakePlaybackStream)
    # No real microphone: conversation capture is faked as in build_window().
    capture = conversation_module.MicrophoneCapture
    monkeypatch.setattr(capture, "start", lambda self: setattr(self, "_stream", object()))
    monkeypatch.setattr(capture, "stop", lambda self: setattr(self, "_stream", None))
    FakeCaptureStream.instances = []
    FakePlaybackStream.played = []
    config = config_without_stt_and_voices(tmp_path)
    provision_stt_and_voices(tmp_path, config)
    config.call_bridge.local_language = local_language
    if configure is not None:
        configure(config, tmp_path)
    pipeline = build_pipeline(config, registry or BUILTIN_REGISTRY, probe=ReadinessProbe(tmp_path))
    window = main_window_module.MainWindow(config, pipeline, persist_settings=False)
    window.call_bridge_panel.enabled_checkbox.setChecked(True)
    window.show()
    return window


def assign(window, *, skip: EndpointRole | None = None) -> None:
    for role, endpoint in mapping().items():
        if role is skip:
            continue
        combo = window.call_bridge_panel.endpoint_combos[role]
        combo.setCurrentIndex(combo.findData(endpoint.endpoint_id))


# The explicit name keeps the fixture "window" for test modules importing this function.
# It requests ``spies``, which the test module imports from ``tests/_spy_window.py``.
@pytest.fixture(name="window")
def call_bridge_window(tmp_path, spies, monkeypatch):
    window = build_call_bridge_window(tmp_path, monkeypatch)
    yield window
    window.stop_call_bridge()
    window.close()


def remove_voice(window, language: str) -> None:
    Path(window.config.tts.voices[language]).unlink()
