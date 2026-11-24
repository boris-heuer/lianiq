"""The Call Bridge setup page: two path boxes, readiness list and Start/Stop (CAP-0166 §2).

The page shows the experimental note with the *Real-call checklist* link, the **You → call**
and **Call → you** path boxes (``call_bridge_paths.CallPathBox``) and the readiness list.
**Start** is enabled only when the injected ``readiness`` callable (the workspace's
``evaluate_readiness``) returns no reason; it is re-evaluated on every selector, language,
model, busy or running change. While another mode holds the session, **Start** also carries
the CAP-0168 ``SESSION_BUSY`` tooltip. ``call_bridge.enabled`` is no longer a gate.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from lianiq.audio.endpoints import EndpointInventory
from lianiq.call_bridge.contracts import (
    AudioEndpointRef,
    EndpointRole,
    LaneId,
    validate_endpoint_assignments,
)
from lianiq.call_bridge.readiness import BlockingReason, configured_assignments
from lianiq.call_bridge.route_tests import RouteTestState
from lianiq.config import PROJECT_ROOT, CallBridgeConfig
from lianiq.ui import strings_call_bridge as s
from lianiq.ui.call_bridge_paths import CallPathBox

OPERATOR_SETUP = PROJECT_ROOT / "docs" / "call-bridge-operator-setup.md"
Readiness = Callable[..., tuple[BlockingReason, ...]]


class CallBridgePanel(QWidget):
    start_requested = Signal()
    stop_requested = Signal()
    route_test_requested = Signal(object)  # LaneId of the path
    route_test_cancelled = Signal(object)
    route_test_answered = Signal(object, bool)
    selection_changed = Signal()

    def __init__(
        self,
        config: CallBridgeConfig,
        *,
        local_name: str,
        remote_name: str,
        readiness: Readiness,
        checklist: Path | None = OPERATOR_SETUP,
    ) -> None:
        super().__init__()
        self.config = config
        self._readiness = readiness
        self._checklist = checklist
        self._endpoints: dict[str, AudioEndpointRef] = {}
        self._inventory: EndpointInventory | None = None
        self._models_ready = False
        self._busy_reason: str | None = None
        self._running = False
        self.reasons: tuple[BlockingReason, ...] | None = None
        self.paths = {path: CallPathBox(path) for path in LaneId}
        self.endpoint_combos = {
            role: combo for box in self.paths.values() for role, combo in box.combos.items()
        }
        self._build_ui()
        self.set_languages(local_name, remote_name)

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        note = QHBoxLayout()
        self.experimental_label = QLabel(s.CB_EXPERIMENTAL)
        self.experimental_label.setWordWrap(True)
        self.experimental_label.setAccessibleName(s.CB_EXPERIMENTAL)
        note.addWidget(self.experimental_label, 1)
        self.checklist_link = QLabel(f'<a href="checklist">{s.CB_CHECKLIST_LINK}</a>')
        self.checklist_link.setAccessibleName(s.CB_CHECKLIST_LINK)
        self.checklist_link.linkActivated.connect(self.open_checklist)
        self.checklist_link.setVisible(self._checklist is not None and self._checklist.is_file())
        note.addWidget(self.checklist_link)
        outer.addLayout(note)
        for box in self.paths.values():
            box.selection_changed.connect(self._selection_changed)
            box.test_requested.connect(self.route_test_requested.emit)
            box.cancel_requested.connect(self.route_test_cancelled.emit)
            box.answered.connect(self.route_test_answered.emit)
            outer.addWidget(box)
        self.readiness_list = QWidget()
        self.readiness_list.setAccessibleName(s.CB_READINESS)
        self._readiness_layout = QVBoxLayout(self.readiness_list)
        self._readiness_layout.setContentsMargins(0, 0, 0, 0)
        self.readiness_labels: list[QLabel] = []
        outer.addWidget(self.readiness_list)
        # CAP-0168 WI-05: Start/Stop sit in their own row, which the workspace keeps outside
        # its scroll area (spec §2.3.7).
        self.session_actions = QWidget()
        actions = QHBoxLayout(self.session_actions)
        actions.setContentsMargins(0, 0, 0, 0)
        self.start_button = QPushButton("Start call bridge")
        self.start_button.clicked.connect(self.start_requested.emit)
        actions.addWidget(self.start_button)
        self.stop_button = QPushButton("Stop call bridge")
        self.stop_button.clicked.connect(self.stop_requested.emit)
        self.stop_button.setEnabled(False)
        actions.addWidget(self.stop_button)
        actions.addStretch(1)

    def open_checklist(self, _link: str = "") -> None:
        """Open the local operator checklist in the default viewer (no network)."""
        if self._checklist is not None and self._checklist.is_file():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._checklist)))

    def set_languages(self, local_name: str, remote_name: str) -> None:
        """Path titles for another pair or local language; readiness is re-evaluated."""
        for box in self.paths.values():
            box.set_languages(local_name, remote_name)
        self.refresh()

    def selected_ids(self) -> dict[EndpointRole, str | None]:
        """The selected (or persisted, not listed) endpoint ID of every role."""
        ids: dict[EndpointRole, str | None] = {}
        for box in self.paths.values():
            ids.update(box.selected_ids())
        return {role: ids.get(role) for role in EndpointRole}

    def assigned_roles(self) -> frozenset[EndpointRole]:
        """Roles with a selected endpoint that is present in the current inventory."""
        return frozenset(
            role for role, value in self.selected_ids().items() if value in self._endpoints
        )

    def endpoint(self, role: EndpointRole) -> AudioEndpointRef | None:
        """The listed endpoint selected for ``role``, else ``None``."""
        return self._endpoints.get(self.selected_ids()[role] or "")

    def set_endpoints(self, endpoints: Iterable[AudioEndpointRef] | None) -> None:
        """The inventory to list; ``None`` when enumeration failed (nothing is listed)."""
        listed = tuple(endpoints) if endpoints is not None else ()
        self._endpoints = {endpoint.endpoint_id: endpoint for endpoint in listed}
        self._inventory = EndpointInventory(listed) if endpoints is not None else None
        configured = configured_assignments(self.config)
        for box in self.paths.values():
            box.set_endpoints(listed, configured)

    def assignments(self) -> dict[EndpointRole, AudioEndpointRef]:
        assignments: dict[EndpointRole, AudioEndpointRef] = {}
        for role, endpoint_id in self.selected_ids().items():
            label = s.CB_ROLE_LABELS[role]
            if endpoint_id is None:
                raise ValueError(s.CB_R_SELECT.format(role=label))
            endpoint = self._endpoints.get(endpoint_id)
            if endpoint is None:
                raise ValueError(s.CB_R_NOT_FOUND.format(role=label))
            assignments[role] = endpoint
        validate_endpoint_assignments(assignments)
        return assignments

    def apply_to_config(self) -> None:
        """Persist the four endpoint IDs; ``call_bridge.enabled`` is never written."""
        for role, endpoint_id in self.selected_ids().items():
            setattr(self.config, f"{role.value}_endpoint_id", endpoint_id)

    def set_models_ready(self, ready: bool) -> None:
        self._models_ready = ready
        self.refresh()

    def set_running(self, running: bool) -> None:
        self._running = running
        for box in self.paths.values():
            box.set_selectors_enabled(not running)
            box.set_stream_open(running)
            # WI-03 drives the lane status lines from ``LaneStatusBook``.
            box.set_lane_status(s.CB_LANE_LISTENING if running else s.CB_LANE_STOPPED)
        self.refresh()

    def set_session_busy(self, reason: str | None) -> None:
        """``reason`` (``SESSION_BUSY``) while another session runs; ``None`` when idle."""
        self._busy_reason = reason
        self.start_button.setToolTip(reason or "")
        self.refresh()

    def set_route_test(
        self, path: LaneId, state: RouteTestState, detail: str, blocked: str
    ) -> None:
        self.paths[path].show_test(state, detail, blocked)

    def _capture_box(self, role: EndpointRole) -> CallPathBox | None:
        return next((box for box in self.paths.values() if box.capture_role is role), None)

    def set_level(self, role: EndpointRole, level: float) -> None:
        if (box := self._capture_box(role)) is not None:
            box.set_level(level)

    def set_clipping(self, role: EndpointRole) -> None:
        if (box := self._capture_box(role)) is not None:
            box.set_clipping()

    def showEvent(self, event) -> None:  # Qt override
        super().showEvent(event)
        self.refresh()  # models or voices may have changed while the page was hidden

    def _selection_changed(self) -> None:
        self.refresh()
        self.selection_changed.emit()

    def refresh(self) -> None:
        """Re-evaluate readiness: the list and **Start** follow it (no blocking work)."""
        reasons = self._readiness(
            self.selected_ids(),
            self._inventory,
            models_ready=self._models_ready,
            busy_reason=self._busy_reason,
            running=self._running,
        )
        self.start_button.setEnabled(not reasons)
        self.stop_button.setEnabled(self._running)
        if reasons == self.reasons:
            return
        self.reasons = reasons
        for label in self.readiness_labels:
            label.setParent(None)
            label.deleteLater()
        self.readiness_labels = []
        for reason in reasons:
            label = QLabel(f"• {reason.text}")
            label.setWordWrap(True)
            label.setAccessibleName(reason.text)
            self._readiness_layout.addWidget(label)
            self.readiness_labels.append(label)
        self.readiness_list.setVisible(bool(reasons))
