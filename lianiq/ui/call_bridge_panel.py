from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGridLayout,
    QGroupBox,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from lianiq.call_bridge.contracts import (
    AudioEndpointRef,
    BridgeState,
    EndpointFlow,
    EndpointRole,
    validate_endpoint_assignments,
)
from lianiq.config import CallBridgeConfig

ROLE_LABELS = {
    EndpointRole.LOCAL_MICROPHONE: "Local microphone · {local} source",
    EndpointRole.CALL_MICROPHONE_RENDER: "Call microphone output · {remote} to call",
    EndpointRole.CALL_SPEAKER_CAPTURE: "Call speaker input · {remote} from call",
    EndpointRole.LOCAL_HEADPHONES: "Local headphones · {local} playback",
}
OUTBOUND_TEST_LABEL = "Test {remote} → call mic"
INBOUND_TEST_LABEL = "Test {local} → headphones"


def role_labels(local: str, remote: str) -> dict[EndpointRole, str]:
    """Role labels for the local and remote language display names of the session pair."""
    return {
        role: template.format(local=local, remote=remote) for role, template in ROLE_LABELS.items()
    }


class CallBridgePanel(QWidget):
    start_requested = Signal()
    stop_requested = Signal()
    route_test_requested = Signal(object)

    def __init__(self, config: CallBridgeConfig, *, local_name: str, remote_name: str) -> None:
        super().__init__()
        self.config = config
        self._language_names = (local_name, remote_name)
        self.role_labels = role_labels(local_name, remote_name)
        self.role_label_widgets: dict[EndpointRole, QLabel] = {}
        self.endpoint_combos: dict[EndpointRole, QComboBox] = {}
        self.level_bars: dict[EndpointRole, QProgressBar] = {}
        self._endpoints: dict[str, AudioEndpointRef] = {}
        self._models_ready = False
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        group = QGroupBox("Full-duplex call bridge")
        layout = QGridLayout(group)

        self.enabled_checkbox = QCheckBox("Enable explicit four-endpoint routing")
        self.enabled_checkbox.setChecked(self.config.enabled)
        self.enabled_checkbox.toggled.connect(self._refresh_enabled_state)
        layout.addWidget(self.enabled_checkbox, 0, 0, 1, 4)

        for row, role in enumerate(EndpointRole, start=1):
            label = QLabel(self.role_labels[role])
            self.role_label_widgets[role] = label
            layout.addWidget(label, row, 0)
            combo = QComboBox()
            label.setBuddy(combo)
            combo.setMinimumContentsLength(28)
            self.endpoint_combos[role] = combo
            layout.addWidget(combo, row, 1, 1, 2)
            if role in {EndpointRole.LOCAL_MICROPHONE, EndpointRole.CALL_SPEAKER_CAPTURE}:
                level = QProgressBar()
                level.setRange(0, 100)
                level.setTextVisible(False)
                self.level_bars[role] = level
                layout.addWidget(level, row, 3)

        self.outbound_test_button = QPushButton()
        self.outbound_test_button.clicked.connect(
            lambda: self.route_test_requested.emit(EndpointRole.CALL_MICROPHONE_RENDER)
        )
        layout.addWidget(self.outbound_test_button, 5, 0)
        self.inbound_test_button = QPushButton()
        self.inbound_test_button.clicked.connect(
            lambda: self.route_test_requested.emit(EndpointRole.LOCAL_HEADPHONES)
        )
        layout.addWidget(self.inbound_test_button, 5, 1)
        self.start_button = QPushButton("Start call bridge")
        self.start_button.clicked.connect(self.start_requested.emit)
        layout.addWidget(self.start_button, 5, 2)
        self.stop_button = QPushButton("Stop call bridge")
        self.stop_button.clicked.connect(self.stop_requested.emit)
        self.stop_button.setEnabled(False)
        layout.addWidget(self.stop_button, 5, 3)

        self.state_label = QLabel("Disabled")
        layout.addWidget(self.state_label, 6, 0, 1, 4)
        outer.addWidget(group)
        self._apply_language_labels(*self._language_names)
        self._refresh_enabled_state()

    def _apply_language_labels(self, local_name: str, remote_name: str) -> None:
        self._language_names = (local_name, remote_name)
        self.role_labels = role_labels(local_name, remote_name)
        for role, label in self.role_label_widgets.items():
            label.setText(self.role_labels[role])
            self.endpoint_combos[role].setAccessibleName(self.role_labels[role])
        self.outbound_test_button.setText(OUTBOUND_TEST_LABEL.format(remote=remote_name))
        self.inbound_test_button.setText(INBOUND_TEST_LABEL.format(local=local_name))

    def set_languages(self, local_name: str, remote_name: str) -> None:
        """Rebuild role labels and test buttons for another pair or local language."""
        self._apply_language_labels(local_name, remote_name)

    def assigned_roles(self) -> frozenset[EndpointRole]:
        """Roles with a selected endpoint that is present in the current inventory."""
        return frozenset(
            role
            for role, combo in self.endpoint_combos.items()
            if combo.currentData() is not None and combo.currentData() in self._endpoints
        )

    def set_endpoints(self, endpoints: Iterable[AudioEndpointRef]) -> None:
        self._endpoints = {endpoint.endpoint_id: endpoint for endpoint in endpoints}
        configured = {
            EndpointRole.LOCAL_MICROPHONE: self.config.local_microphone_endpoint_id,
            EndpointRole.CALL_MICROPHONE_RENDER: self.config.call_microphone_render_endpoint_id,
            EndpointRole.CALL_SPEAKER_CAPTURE: self.config.call_speaker_capture_endpoint_id,
            EndpointRole.LOCAL_HEADPHONES: self.config.local_headphones_endpoint_id,
        }
        for role, combo in self.endpoint_combos.items():
            combo.clear()
            combo.addItem("Select an endpoint …", None)
            expected_flow = (
                EndpointFlow.CAPTURE
                if role in {EndpointRole.LOCAL_MICROPHONE, EndpointRole.CALL_SPEAKER_CAPTURE}
                else EndpointFlow.RENDER
            )
            for endpoint in self._endpoints.values():
                if endpoint.flow is not expected_flow:
                    continue
                label = (
                    f"{endpoint.display_name} · {endpoint.host_api} · "
                    f"{endpoint.channels} ch / {endpoint.sample_rate} Hz"
                )
                combo.addItem(label, endpoint.endpoint_id)
            selected = combo.findData(configured[role])
            combo.setCurrentIndex(max(selected, 0))
        self._refresh_enabled_state()

    def assignments(self) -> dict[EndpointRole, AudioEndpointRef]:
        assignments: dict[EndpointRole, AudioEndpointRef] = {}
        for role, combo in self.endpoint_combos.items():
            endpoint_id = combo.currentData()
            if endpoint_id is None:
                raise ValueError(f"Select an endpoint for {self.role_labels[role]}")
            endpoint = self._endpoints.get(endpoint_id)
            if endpoint is None:
                raise ValueError(f"Configured endpoint is unavailable for {self.role_labels[role]}")
            assignments[role] = endpoint
        validate_endpoint_assignments(assignments)
        return assignments

    def apply_to_config(self) -> None:
        self.config.enabled = self.enabled_checkbox.isChecked()
        values = {role: combo.currentData() for role, combo in self.endpoint_combos.items()}
        self.config.local_microphone_endpoint_id = values[EndpointRole.LOCAL_MICROPHONE]
        self.config.call_microphone_render_endpoint_id = values[EndpointRole.CALL_MICROPHONE_RENDER]
        self.config.call_speaker_capture_endpoint_id = values[EndpointRole.CALL_SPEAKER_CAPTURE]
        self.config.local_headphones_endpoint_id = values[EndpointRole.LOCAL_HEADPHONES]

    def set_models_ready(self, ready: bool) -> None:
        self._models_ready = ready
        self._refresh_enabled_state()

    def set_running(self, running: bool) -> None:
        self.enabled_checkbox.setEnabled(not running)
        for combo in self.endpoint_combos.values():
            combo.setEnabled(not running)
        ready = not running and self.enabled_checkbox.isChecked() and self._models_ready
        self.start_button.setEnabled(ready)
        self.stop_button.setEnabled(running)
        self.outbound_test_button.setEnabled(ready)
        self.inbound_test_button.setEnabled(ready)
        self.state_label.setText("Running" if running else "Ready")

    def set_state(self, state: BridgeState | str, message: str = "") -> None:
        value = state.value if isinstance(state, BridgeState) else state
        self.state_label.setText(f"{value.replace('_', ' ').title()}: {message}".rstrip(": "))

    def set_level(self, role: EndpointRole, level: float) -> None:
        bar = self.level_bars.get(role)
        if bar is not None:
            bar.setValue(round(max(0.0, min(level, 1.0)) * 100))

    def _refresh_enabled_state(self) -> None:
        enabled = self.enabled_checkbox.isChecked()
        for combo in self.endpoint_combos.values():
            combo.setEnabled(enabled)
        self.start_button.setEnabled(enabled and self._models_ready)
        self.outbound_test_button.setEnabled(enabled and self._models_ready)
        self.inbound_test_button.setEnabled(enabled and self._models_ready)
        if not enabled:
            self.state_label.setText("Disabled")
