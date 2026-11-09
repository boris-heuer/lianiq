"""Start, stop, languages and events of ``CallBridgeWorkspace`` (CAP-0168 file-size split)."""

from __future__ import annotations

from PySide6.QtCore import Slot
from PySide6.QtWidgets import QVBoxLayout, QWidget

from lianiq.call_bridge.contracts import (
    BridgeEvent,
    BridgeEventKind,
    BridgeState,
    CallBridgeLanes,
    EndpointRole,
    LaneId,
)
from lianiq.call_bridge.controller import check_call_bridge
from lianiq.languages.modes import CALL_BRIDGE_MODE, SessionPair
from lianiq.ui import notice_catalog as catalog
from lianiq.ui import strings
from lianiq.ui.call_bridge_panel import CallBridgePanel
from lianiq.ui.shell.session_owner import SessionBusy, SessionState
from lianiq.ui.shell.workspaces import WorkspaceId, session_busy_message

CALL_BRIDGE = WorkspaceId.CALL_BRIDGE


class CallBridgeLifecycle:
    """``CallBridgeWorkspace`` base: the panel, Start and Stop, lane names and events."""

    def build_page(self) -> QWidget:
        """The Call Bridge page: the panel with its explicit endpoint selectors."""
        page = QWidget()
        page.setObjectName("callBridgePage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.build_panel())
        layout.addStretch(1)
        return page

    def build_panel(self) -> CallBridgePanel:
        local_name, remote_name = self._language_names()
        self.panel = CallBridgePanel(
            self.config.call_bridge, local_name=local_name, remote_name=remote_name
        )
        self.panel.start_requested.connect(self.start_call_bridge)
        self.panel.stop_requested.connect(self.stop_call_bridge)
        self.panel.route_test_requested.connect(self._run_call_bridge_route_test)
        return self.panel

    def active(self) -> bool:
        """A Call Bridge runs or loads its models."""
        return self.controller is not None or self.starting

    def session(self) -> SessionPair:
        registry = self.pipeline.registry
        return SessionPair(
            registry.pair(*self.config.languages.pair),
            CALL_BRIDGE_MODE,
            local_language=registry.get(self.config.call_bridge.local_language).id,
        )

    def _language_names(self) -> tuple[str, str]:
        """Registry names of the local and remote Call Bridge languages for the panel."""
        try:
            lanes = CallBridgeLanes.from_session(self.session())
        except Exception:  # noqa: BLE001 - an invalid setting is reported on Start.
            return "local language", "remote language"
        registry = self.pipeline.registry
        return registry.display_name(lanes.local), registry.display_name(lanes.remote)

    def update_languages(self) -> None:
        self.panel.set_languages(*self._language_names())

    def lanes_name(self) -> str:
        """The Call Bridge languages for its notices: "<local> ↔ <remote>"."""
        local, remote = self._language_names()
        return strings.PAIR_NAME.format(a=local, b=remote)

    def _lane_source(self, lane: LaneId | None) -> str:
        """The lane and the language it listens to: "Call Bridge · outbound · German"."""
        if lane is None:
            return catalog.source(CALL_BRIDGE, self.lanes_name())
        try:
            language = CallBridgeLanes.from_session(self.session()).edge(lane).source
        except Exception:  # noqa: BLE001 - an invalid setting: name the lane only.
            return catalog.source(CALL_BRIDGE, lane.value)
        name = self.pipeline.registry.display_name(language)
        return catalog.source(CALL_BRIDGE, lane.value, name)

    def _error(self, message: str) -> None:
        self.host.show_error(message, CALL_BRIDGE)

    @Slot()
    def start_call_bridge(self) -> None:
        if self.active():
            return
        host = self.host
        try:
            session = self.session()
            # Requirement row 7 before any model loads: name every missing item.
            availability = check_call_bridge(
                session, self.pipeline.catalog, self.panel.assigned_roles()
            )
        except Exception as exc:  # noqa: BLE001 - GUI boundary reports setup failures.
            self._error(str(exc))
            return
        if not availability.available:
            host.show_unavailable(availability.missing, CALL_BRIDGE)
            return
        try:
            assignments = self.panel.assignments()
        except Exception as exc:  # noqa: BLE001 - GUI boundary reports setup failures.
            self._error(str(exc))
            return
        try:
            self._generation = self.owner.request_start(WorkspaceId.CALL_BRIDGE)
        except SessionBusy as busy:
            # Nothing was opened; the running session continues (an info notice).
            host.show_busy(CALL_BRIDGE, busy.active)
            return
        conversation = host.conversation
        self.starting = True
        self._pending_assignments = assignments
        self._pending_session = session
        self.panel.set_models_ready(False)
        conversation.start_button.setEnabled(False)
        host.statusBar().showMessage("Loading the call bridge models …")
        host.prepare_in_background(session, host.bridge.call_bridge_ready)

    @Slot(int, bool, str)
    def _call_bridge_ready(self, generation: int, ready: bool, message: str) -> None:
        if not self.starting or generation != self.host.start_generation:
            return
        self.starting = False
        assignments, self._pending_assignments = self._pending_assignments, None
        session, self._pending_session = self._pending_session, None
        self.panel.set_models_ready(True)
        if not ready or assignments is None or session is None:
            self.owner.mark_idle(self._generation)
            # Start follows the selected mode's availability
            self.host.conversation.refresh_availability()
            reason = message or "Call bridge setup was cancelled"
            self.host.post_notice(
                catalog.model_failed(
                    CALL_BRIDGE, reason, self._lane_source(None), self.start_call_bridge
                )
            )
            return
        self._begin_call_bridge(assignments, session)

    @Slot()
    def stop_call_bridge(self) -> None:
        self._endpoint_monitor.stop()
        controller, self.controller = self.controller, None
        if controller is not None and not controller.stop(timeout=10.0):
            self._error("Call bridge workers did not stop within the shutdown contract")
        self.starting = False
        self._pending_assignments = None
        self._pending_session = None
        if self.owner.active is WorkspaceId.CALL_BRIDGE:
            self.owner.mark_idle(self._generation)
        self.panel.set_running(False)
        self.panel.set_models_ready(True)
        conversation = self.host.conversation
        idle = not conversation.starting and not conversation.capture.running
        conversation.start_button.setEnabled(idle)
        conversation.set_session_controls_enabled(idle)
        conversation.set_devices_enabled(True)
        for role in (EndpointRole.LOCAL_MICROPHONE, EndpointRole.CALL_SPEAKER_CAPTURE):
            self.panel.set_level(role, 0.0)
        self.host.statusBar().showMessage(
            "Call bridge stopped; all explicit endpoints were released"
        )

    def _session_changed(self, state: SessionState, active: WorkspaceId | None) -> None:
        """While another mode holds the session, the panel's **Start** says why it is off."""
        busy = state is not SessionState.IDLE and active is not WorkspaceId.CALL_BRIDGE
        self.panel.set_session_busy(
            session_busy_message(active) if busy and active is not None else None
        )

    @Slot(object, str)
    def _handle_call_bridge_capture_fault(self, role: EndpointRole, message: str) -> None:
        if self.controller is not None:
            self.controller.endpoint_lost(role)
        lane = LaneId.OUTBOUND if role is EndpointRole.LOCAL_MICROPHONE else LaneId.INBOUND
        self.host.post_notice(catalog.bridge_capture_muted(message, self._lane_source(lane)))

    @Slot(object)
    def _show_call_bridge_event(self, event: BridgeEvent) -> None:
        if event.kind is BridgeEventKind.STATE:
            self.panel.set_state(event.category)
        elif event.kind is BridgeEventKind.ERROR:
            if event.category == "playback_failure" and self.controller is not None:
                output_role = (
                    EndpointRole.CALL_MICROPHONE_RENDER
                    if event.lane_id is LaneId.OUTBOUND
                    else EndpointRole.LOCAL_HEADPHONES
                )
                self.controller.endpoint_lost(output_role)
            self.panel.set_state(BridgeState.DEGRADED, event.category)
            lane = event.lane_id.value if event.lane_id else None
            self.host.diagnostics.record("call-bridge", f"{event.category}: {event.message}")
            self.host.post_notice(
                catalog.bridge_failed(lane, event.category, self._lane_source(event.lane_id))
            )
        elif event.kind is BridgeEventKind.DROPPED:
            self.host.post_notice(
                catalog.bridge_dropped(event.category, self._lane_source(event.lane_id))
            )
        elif event.kind is BridgeEventKind.ENDPOINT:
            self.panel.set_state(
                BridgeState.DEGRADED if event.category == "endpoint_lost" else BridgeState.RUNNING,
                event.message,
            )

    @Slot(object, float)
    def _show_call_bridge_level(self, role: EndpointRole, level: float) -> None:
        self.panel.set_level(role, level)
