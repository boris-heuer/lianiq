"""Start, stop, languages and events of ``CallBridgeWorkspace`` (CAP-0168 file-size split).

session-status-truthfulness WI-05 (§2.2.4, AC-19): **Stop call bridge** and F9 both go
through ``owner.stop()``. The stopper is asynchronous: captures close on the GUI thread,
both lanes stop in parallel on a ``call-bridge-stop`` worker, and ``call_bridge_stopped``
hands the ``LaneStopResult`` back. A lane that timed out reads *Did not stop in time*,
``session.stop-timeout`` shows and ``owner.linger`` refuses every Start while it lives.
"""

from __future__ import annotations

import logging
import threading

from PySide6.QtCore import Slot
from PySide6.QtWidgets import QVBoxLayout, QWidget

from lianiq.call_bridge.contracts import CallBridgeLanes, EndpointRole, LaneId
from lianiq.call_bridge.controller import LaneStopResult, check_call_bridge
from lianiq.languages.modes import CALL_BRIDGE_MODE, SessionPair
from lianiq.packs.protection import ActiveUsage
from lianiq.ui import notice_catalog as catalog
from lianiq.ui import strings
from lianiq.ui.call_bridge_panel import CallBridgePanel
from lianiq.ui.shell.scroll import workspace_scroll
from lianiq.ui.shell.session_owner import SessionBusy, SessionState
from lianiq.ui.shell.workspaces import WorkspaceId, session_busy_message
from lianiq.ui.transcript.replay import end_playback

CALL_BRIDGE = WorkspaceId.CALL_BRIDGE
LOGGER = logging.getLogger(__name__)


class CallBridgeLifecycle:
    """``CallBridgeWorkspace`` base: the panel, Start and Stop, lane names and events."""

    def build_page(self) -> QWidget:
        """The Call Bridge page: the panel with its explicit endpoint selectors."""
        page = QWidget()
        page.setObjectName("callBridgePage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        # WI-05 (spec §2.3.7): the panel scrolls; its Start/Stop row stays outside.
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.addWidget(self.build_panel())
        content_layout.addStretch(1)
        layout.addWidget(workspace_scroll(content), 1)
        layout.addWidget(self.panel.session_actions)
        return page

    def build_panel(self) -> CallBridgePanel:
        local_name, remote_name = self._language_names()
        self.panel = CallBridgePanel(
            self.config.call_bridge,
            local_name=local_name,
            remote_name=remote_name,
            readiness=self.readiness_reasons,
        )
        self.panel.start_requested.connect(self.start_call_bridge)
        self.panel.stop_requested.connect(self.stop_call_bridge)
        self.connect_setup(self.panel)
        self.show_route_tests()
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
        self.show_route_tests()  # a pair or local-language change resets both paths

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
        if self.active() or self.route_test_active():
            return  # a playing or unanswered route test blocks Start (readiness names it)
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
        end_playback(host, WorkspaceId.CALL_BRIDGE)  # a transcript replay ends first
        try:
            self._generation = self.owner.request_start(WorkspaceId.CALL_BRIDGE)
        except SessionBusy as busy:
            # Nothing was opened; the running session continues (an info notice).
            host.show_busy(CALL_BRIDGE, busy.active)
            return
        self.reset_status(self._generation, session)  # *Starting…*; the live text clears
        conversation = host.conversation
        # Both lanes always speak: their voice options are bound now (CAP-0167 C §5, AC-18).
        self.voice_options = conversation.voice_preferences.snapshot(session.pair.members)
        voices = frozenset(self.voice_options)
        host.usage_tracker.bind(ActiveUsage(CALL_BRIDGE, session, False, voices))
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
            self.stop_status()
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
        """**Stop call bridge** (and ``MainWindow.stop_call_bridge``): through the owner."""
        if self.owner.active is CALL_BRIDGE:
            self.owner.stop()  # a no-op while already stopping
        elif not self.active():
            self._show_stopped(bool(self._lanes_not_stopped))

    def _stop_session(self) -> None:
        """The owner's asynchronous stopper: captures now, both lanes on a worker."""
        self._endpoint_monitor.stop()
        controller, self.controller = self.controller, None
        self.starting = False
        self._pending_assignments = None
        self._pending_session = None
        generation = self._generation
        if controller is None:  # models still loading: nothing was opened
            self._call_bridge_stopped(generation, None)
            return
        controller.stop_captures()  # GUI thread: level bars 0 at once
        self._stopping_controller = controller
        timeout, stopped = self.lane_stop_timeout, self.host.bridge.call_bridge_stopped

        def stop_lanes() -> None:
            try:
                result = controller.stop_lanes(timeout)
            except Exception:  # worker boundary: report both lanes as not stopped
                LOGGER.exception("Call bridge lane stop failed")
                result = LaneStopResult(False, False)
            try:
                stopped.emit(generation, result)
            except RuntimeError:  # the window was destroyed while the lanes stopped
                pass

        threading.Thread(target=stop_lanes, name="call-bridge-stop", daemon=True).start()

    @Slot(int, object)
    def _call_bridge_stopped(self, generation: int, result: LaneStopResult | None) -> None:
        """The lanes of ``generation`` ended or timed out (GUI thread)."""
        if generation != self._generation:
            return
        controller, self._stopping_controller = self._stopping_controller, None
        self._results_generation = None  # a late lane result is not shown
        timed_out = () if result is None else result.timed_out
        self._lanes_not_stopped = frozenset(timed_out)
        if timed_out and controller is not None:
            self.owner.linger(CALL_BRIDGE, controller.alive)
            self.host.post_notice(catalog.stop_timeout(CALL_BRIDGE, len(timed_out), generation))
        self.owner.mark_idle(generation)
        self._show_stopped(bool(timed_out))

    def _show_stopped(self, timed_out: bool) -> None:
        self.stop_status()  # *Stopped* or *Did not stop in time*; the live text stays
        self.panel.set_running(False)
        self.panel.set_models_ready(True)
        conversation = self.host.conversation
        idle = not conversation.starting and not conversation.capture.running
        conversation.start_button.setEnabled(idle)
        conversation.set_session_controls_enabled(idle)
        conversation.set_devices_enabled(True)
        self.host.statusBar().showMessage(
            "Call bridge stopped; a lane did not stop in time"
            if timed_out
            else "Call bridge stopped; all explicit endpoints were released"
        )

    def _session_changed(self, state: SessionState, active: WorkspaceId | None) -> None:
        """While another mode holds the session, the panel's **Start** says why it is off."""
        busy = state is not SessionState.IDLE and active is not WorkspaceId.CALL_BRIDGE
        self.panel.set_session_busy(
            session_busy_message(active) if busy and active is not None else None
        )
        self.show_route_tests()  # tests are disabled while the Call Bridge runs

    @Slot(object, float)
    def _show_call_bridge_level(self, role: EndpointRole, level: float) -> None:
        self.panel.set_level(role, level)
