"""Settings › Audio devices: Microphone and Speakers by endpoint identity (CAP-0168 WI-04).

Spec §2.3.5, contract §4 and §7. The combos list the Conversation inventory
(``device_inventory.read_inventory``) with ``display_labels``; the first item follows the
Windows default and names it. A saved device that is missing stays selected as
"<name> — unavailable", an unusable endpoint is listed disabled with its reason, and no
other device is ever selected silently. Tooltips and accessible descriptions give the full
name, host API and channels, never an endpoint ID. Choices are saved per contract §7.

The bases hold the unavailable-device notices and **Refresh** (``DeviceRefresh``), the
loss monitor and the Conversation no-signal warning (``DeviceWatch``) and **Test
microphone** / **Test speakers** (``DeviceTests``).
"""

from __future__ import annotations

import time
from dataclasses import replace

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QComboBox, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QPushButton

from lianiq.audio.device_inventory import read_inventory, read_native_ids, reinitialize_portaudio
from lianiq.audio.device_selection import (
    FOLLOW_DEFAULT,
    DeviceChoice,
    DevicePolicy,
    ResolvedDevice,
    UnusableEndpoint,
    choice_from_settings,
    describe,
    display_labels,
    is_legacy,
    resolve_choice,
    store_choice,
    unusable_reason,
)
from lianiq.audio.device_state import DeviceState
from lianiq.call_bridge.contracts import EndpointFlow
from lianiq.ui import notice_catalog as catalog
from lianiq.ui import strings
from lianiq.ui.device_refresh import DeviceRefresh
from lianiq.ui.device_tests import DeviceTests
from lianiq.ui.device_watch import CAPTURE, FLOW_NAMES, RENDER, DeviceWatch

MISSING = "\x00missing"  # combo data of the "<name> — unavailable" item


class DeviceSetup(DeviceRefresh, DeviceWatch, DeviceTests, QObject):
    test_level = Signal(float)  # Test microphone level, from the PortAudio thread
    tone_done = Signal(str)  # Test speakers finished: "" or the failure reason

    def __init__(self, host) -> None:
        super().__init__(host)
        self.host = host
        self.config = host.config
        self.clock = time.monotonic
        # Looked up on this module at call time, so tests replace the reads with fakes.
        self.state = DeviceState(
            lambda: read_inventory(), lambda: reinitialize_portaudio(), lambda: read_native_ids()
        )
        self.choices: dict[EndpointFlow, DeviceChoice] = {
            CAPTURE: FOLLOW_DEFAULT,
            RENDER: FOLLOW_DEFAULT,
        }
        self.active: dict[EndpointFlow, ResolvedDevice] = {}  # opened by the running session
        self.testing = False
        self.init_watch()
        self.init_tests()

    def build_group(self) -> QGroupBox:
        group = QGroupBox(strings.AUDIO_DEVICES)
        grid = QGridLayout(group)
        self.combos: dict[EndpointFlow, QComboBox] = {}
        for row, flow in enumerate((CAPTURE, RENDER)):
            caption = QLabel(FLOW_NAMES[flow])
            combo = QComboBox()
            combo.setAccessibleName(FLOW_NAMES[flow])
            caption.setBuddy(combo)
            combo.setSizeAdjustPolicy(
                QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
            )
            combo.setMinimumContentsLength(10)
            combo.currentIndexChanged.connect(lambda _index, flow=flow: self._combo_changed(flow))
            grid.addWidget(caption, row, 0)
            grid.addWidget(combo, row, 1)
            self.combos[flow] = combo
        self.input_combo, self.output_combo = self.combos[CAPTURE], self.combos[RENDER]
        grid.setColumnStretch(1, 1)
        buttons = QHBoxLayout()
        self.refresh_button = QPushButton(strings.DEVICE_REFRESH)
        self.refresh_button.setAccessibleName(strings.DEVICE_REFRESH)
        self.refresh_button.clicked.connect(self.refresh)
        buttons.addWidget(self.refresh_button)
        self.build_tests(buttons, grid, 3)
        grid.addLayout(buttons, 2, 0, 1, 2)
        return group

    # Inventory and choices --------------------------------------------------------------

    @property
    def devices(self) -> list:
        return list(self.state.inventory.endpoints)

    @devices.setter
    def devices(self, endpoints) -> None:
        """Replace the listed endpoints (tests); the defaults keep their identities."""
        self.state.inventory = replace(self.state.inventory, endpoints=tuple(endpoints))
        self.fill()

    def resolved(self, flow: EndpointFlow) -> ResolvedDevice:
        inventory = self.state.inventory
        return resolve_choice(
            self.choices[flow], inventory.endpoints, flow, inventory.default(flow)
        )

    def load(self) -> bool:
        """The start-up read and the contract §7 choices; ``False`` (reported) on failure."""
        try:
            self.state.load()
        except (OSError, RuntimeError, ValueError) as exc:
            self.host.bridge.error.emit(str(exc))
            return False
        inventory, audio = self.state.inventory, self.config.audio
        for flow in (CAPTURE, RENDER):
            legacy = is_legacy(audio, flow)
            choice = choice_from_settings(audio, flow, inventory.legacy_names, inventory.endpoints)
            self.choices[flow] = choice
            store_choice(audio, flow, choice)  # the index keys are ``null`` from now on
            if legacy:
                name = choice.display_name or strings.DEVICE_SAVED
                self.host.post_notice(catalog.device_migrated(FLOW_NAMES[flow], name, self.where()))
        self.fill()
        return True

    def fill(self) -> None:
        endpoints = self.state.inventory.endpoints
        labels = display_labels(endpoints)
        for flow, combo in self.combos.items():
            combo.blockSignals(True)
            combo.clear()
            default = self.state.inventory.default(flow)
            combo.addItem(resolve_choice(FOLLOW_DEFAULT, endpoints, flow, default).label, None)
            if default is not None:
                combo.setItemData(0, describe(default), Qt.ItemDataRole.ToolTipRole)
            for endpoint in endpoints:
                if endpoint.flow is not flow:
                    continue
                text = labels[endpoint.endpoint_id]
                unusable = isinstance(endpoint, UnusableEndpoint)
                if unusable:
                    text = strings.DEVICE_UNUSABLE.format(name=text, reason=unusable_reason(flow))
                combo.addItem(text, endpoint.endpoint_id)
                index = combo.count() - 1
                combo.setItemData(index, describe(endpoint), Qt.ItemDataRole.ToolTipRole)
                combo.model().item(index).setEnabled(not unusable)
            combo.setCurrentIndex(self._choice_index(flow, combo))
            self._describe(flow)
            combo.blockSignals(False)
        self.post_unavailable()

    def _choice_index(self, flow: EndpointFlow, combo: QComboBox) -> int:
        choice = self.choices[flow]
        if choice.policy is DevicePolicy.FOLLOW_DEFAULT:
            return 0
        index = combo.findData(choice.endpoint_id) if choice.endpoint_id else -1
        if index < 0:  # the saved device stays selected, shown as unavailable
            combo.addItem(self.resolved(flow).label, MISSING)
            index = combo.count() - 1
            combo.model().item(index).setEnabled(False)
        return index

    def _describe(self, flow: EndpointFlow) -> None:
        combo, resolved = self.combos[flow], self.resolved(flow)
        target = resolved.endpoint
        text = resolved.label if target is None else f"{resolved.label} · {describe(target)}"
        combo.setToolTip(text)
        combo.setAccessibleDescription(text)

    def _combo_changed(self, flow: EndpointFlow) -> None:
        data = self.combos[flow].currentData()
        if data == MISSING:
            return
        if data is None:
            choice = FOLLOW_DEFAULT
        else:
            endpoint = next(e for e in self.state.inventory.endpoints if e.endpoint_id == data)
            choice = DeviceChoice(DevicePolicy.EXPLICIT, data, endpoint.display_name)
        self.choices[flow] = choice
        store_choice(self.config.audio, flow, choice)
        self.fill()  # drops a "— unavailable" item that is no longer selected
        self.host.conversation.refresh_availability()

    def set_enabled(self, enabled: bool) -> None:
        """The active devices never change while a session runs."""
        for combo in self.combos.values():
            combo.setEnabled(enabled)
