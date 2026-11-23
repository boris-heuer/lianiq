"""Setup assistant step 3, *Audio check* (CAP-0171 spec §2.2.1 item 4, AC-06, AC-29).

Only the device roles of the ticked usages, each with its CAP-0168 device name or *Not
found*. **Test microphone** reuses the Settings test (``DeviceSetup.test_microphone``: the
Conversation input for at most 5 s) and mirrors its level meter; **Play test sound** plays
the generated 1 s 440 Hz tone from memory on the Conversation output, so no file is
written. Missing devices never block **Next**. ``play_pcm`` is looked up on this module.
"""

from __future__ import annotations

import threading
from collections.abc import Sequence

from PySide6.QtCore import QTimer, Signal, Slot
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from lianiq.audio.playback import play_pcm
from lianiq.call_bridge.contracts import EndpointFlow, EndpointRole
from lianiq.languages.requirements import CALL_ENDPOINT_ROLES, MEETING_ENDPOINT_ROLES
from lianiq.meeting.contracts import MeetingRole
from lianiq.packs.usage import UsageProfile
from lianiq.ui import strings
from lianiq.ui.device_tests import MIC_TEST_SECONDS, TONE_RATE, tone_samples

CAPTURE, RENDER = EndpointFlow.CAPTURE, EndpointFlow.RENDER


def _conversation(host, flow: EndpointFlow) -> str | None:
    setup = host.device_setup
    return setup.device_name(flow) if setup.resolved(flow).ready else None


def _call_bridge(host, role: str) -> str | None:
    panel = host.call_bridge_panel
    if EndpointRole(role) not in panel.assigned_roles():
        return None
    return panel._endpoints[panel.endpoint_combos[EndpointRole(role)].currentData()].display_name


def _meeting(host, role: str) -> str | None:
    endpoint = host.meeting.endpoint(MeetingRole(role))
    return None if endpoint is None else endpoint.display_name


def role_devices(host, profile: UsageProfile) -> list[tuple[str, str | None]]:
    """(role label, device name or ``None``) for each device role of ``profile`` (C §7)."""
    if profile.id == "conversation":
        found = [_conversation(host, flow) for flow in (CAPTURE, RENDER)]
    elif profile.id == "call-bridge":
        found = [_call_bridge(host, role) for role in CALL_ENDPOINT_ROLES]
    elif profile.id == "meeting":
        found = [_meeting(host, role) for role in MEETING_ENDPOINT_ROLES]
    else:
        found = [None] * len(profile.device_roles)
    return list(zip(profile.device_roles, found, strict=True))


class AudioStep(QWidget):
    tone_done = Signal(str)  # "" or the failure reason, from the playback thread

    def __init__(self, host) -> None:
        super().__init__()
        self.host = host
        layout = QVBoxLayout(self)
        title = QLabel(strings.ASSIST_AUDIO_TITLE)
        title.setObjectName("panelTitle")
        layout.addWidget(title)
        self.roles = QVBoxLayout()
        layout.addLayout(self.roles)
        self.role_labels: list[QLabel] = []
        buttons = QHBoxLayout()
        self.test_mic_button = QPushButton(strings.ASSIST_TEST_MIC)
        self.test_sound_button = QPushButton(strings.ASSIST_TEST_SOUND)
        self.meter = QProgressBar()
        self.meter.setRange(0, 100)
        self.meter.setTextVisible(False)
        self.meter.setAccessibleName(strings.ASSIST_TEST_MIC)
        for button in (self.test_mic_button, self.test_sound_button):
            button.setAccessibleName(button.text())
            buttons.addWidget(button)
        buttons.addWidget(self.meter, 1)
        layout.addLayout(buttons)
        self.result = QLabel()
        self.result.setWordWrap(True)
        layout.addWidget(self.result)
        layout.addStretch(1)
        self.test_mic_button.clicked.connect(self.test_microphone)
        self.test_sound_button.clicked.connect(self.play_test_sound)
        host.device_setup.test_level.connect(self._level)
        self.tone_done.connect(self._tone_done)
        self._mic_timer = QTimer(self, singleShot=True, interval=int(MIC_TEST_SECONDS * 1000))
        self._mic_timer.timeout.connect(lambda: self.meter.setValue(0))

    def show_roles(self, profiles: Sequence[UsageProfile]) -> None:
        while self.roles.count():
            self.roles.takeAt(0).widget().deleteLater()
        self.role_labels = []
        for profile in profiles:
            if not profile.device_roles:
                continue
            group = QGroupBox(profile.label)
            group.setAccessibleName(profile.label)
            column = QVBoxLayout(group)
            for role, name in role_devices(self.host, profile):
                label = QLabel(f"{role}: {name or strings.ASSIST_DEVICE_MISSING}")
                label.setAccessibleName(label.text())
                column.addWidget(label)
                self.role_labels.append(label)
            self.roles.addWidget(group)

    @Slot()
    def test_microphone(self) -> None:
        setup = self.host.device_setup
        setup.test_microphone()
        self.result.setText(setup.test_result.text())
        if setup.testing:
            self._mic_timer.start()

    @Slot(float)
    def _level(self, level: float) -> None:
        if self._mic_timer.isActive():
            self.meter.setValue(round(level * 100))
            self.result.setText(self.host.device_setup.test_result.text())

    @Slot()
    def play_test_sound(self) -> None:
        setup = self.host.device_setup
        if setup.streams_open():
            return
        resolved = setup.resolved(RENDER)
        if resolved.endpoint is None:
            self.result.setText(resolved.label)
            return
        index, emit = resolved.endpoint.runtime_index, self.tone_done.emit
        self.test_sound_button.setEnabled(False)

        def play() -> None:
            try:
                play_pcm(tone_samples(), TONE_RATE, index, auto_convert=True)
            except Exception as exc:  # noqa: BLE001 - shown in the step
                emit(str(exc) or type(exc).__name__)
                return
            emit("")

        threading.Thread(target=play, name="assistant-tone", daemon=True).start()

    @Slot(str)
    def _tone_done(self, reason: str) -> None:
        self.test_sound_button.setEnabled(True)
        if reason:
            mode = strings.ASSIST_TEST_SOUND
            self.result.setText(strings.NOTICE_START_FAILED.format(mode=mode, reason=reason))
        else:
            name = self.host.device_setup.device_name(RENDER)
            self.result.setText(strings.ASSIST_SOUND_PLAYED.format(name=name))
