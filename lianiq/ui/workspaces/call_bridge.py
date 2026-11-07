"""The Call Bridge workspace: lanes, endpoints, route tests and recovery (CAP-0168 WI-01).

Moved behaviour-neutrally out of ``ui/main_window.py``. The workspace owns the
``CallBridgePanel`` and the running ``FullDuplexBridgeController``; ``MainWindow`` provides
the shared status bar, session lock and model warm-up.

CAP-0168 WI-02: the panel is the workspace's own page (sidebar entry *Call Bridge*,
"Experimental") with its explicit endpoint selectors only. A start goes through
``ActiveSessionOwner.request_start``: while the conversation holds the session it is refused
with ``SESSION_BUSY`` and opens no stream, and the panel's **Start** is disabled with that
tooltip. A running conversation is never stopped by a Call Bridge start any more.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QTimer, Slot
from PySide6.QtWidgets import QVBoxLayout, QWidget

from lianiq.audio.capture_stream import EndpointCaptureStream
from lianiq.audio.endpoints import list_audio_endpoints
from lianiq.audio.playback_stream import EndpointPlaybackStream
from lianiq.call_bridge.contracts import (
    BridgeEvent,
    BridgeEventKind,
    BridgeState,
    CallBridgeLanes,
    EndpointRole,
    LaneId,
)
from lianiq.call_bridge.controller import FullDuplexBridgeController, check_call_bridge
from lianiq.call_bridge.inference_scheduler import InferenceScheduler
from lianiq.call_bridge.translation_lane import TranslationLane
from lianiq.languages.errors import ModeUnavailableError
from lianiq.languages.modes import CALL_BRIDGE_MODE, SessionPair
from lianiq.languages.registry import LanguageId
from lianiq.ui.call_bridge_panel import CallBridgePanel
from lianiq.ui.shell.session_owner import SessionBusy, SessionState
from lianiq.ui.shell.workspaces import WorkspaceId, session_busy_message

if TYPE_CHECKING:
    from lianiq.ui.main_window import MainWindow

# Route-test phrases per language (functional data). The Call Bridge lanes themselves come
# from the session pair and ``call_bridge.local_language`` (``CallBridgeLanes``).
ROUTE_TEST_TEXT = {LanguageId("de"): "Kopfhörer-Test.", LanguageId("zh-Hans"): "通话麦克风测试。"}


class CallBridgeWorkspace(QObject):
    def __init__(self, host: MainWindow) -> None:
        super().__init__(host)
        self.host = host
        self.config = host.config
        self.pipeline = host.pipeline
        bridge = host.bridge
        bridge.call_bridge_ready.connect(self._call_bridge_ready)
        bridge.call_bridge_event.connect(self._show_call_bridge_event)
        bridge.call_bridge_level.connect(self._show_call_bridge_level)
        bridge.call_bridge_capture_fault.connect(self._handle_call_bridge_capture_fault)
        self.controller: FullDuplexBridgeController | None = None
        self.starting = False
        self._pending_assignments = None
        self._pending_session: SessionPair | None = None
        self._endpoint_monitor = QTimer(self)
        self._endpoint_monitor.setInterval(2_000)
        self._endpoint_monitor.timeout.connect(self._reconcile_call_bridge_endpoints)
        self.owner = host.session_owner
        self._generation = 0  # the owner generation of this workspace's latest start
        self.owner.register(WorkspaceId.CALL_BRIDGE, self.stop_call_bridge)
        self.owner.subscribe(self._session_changed)

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

    def load_endpoints(self) -> None:
        try:
            inventory = list_audio_endpoints()
        except (RuntimeError, ValueError) as exc:
            self.panel.set_endpoints([])
            self.panel.set_state("unavailable", str(exc))
        else:
            self.panel.set_endpoints(inventory.endpoints)

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
            host.show_error(str(exc))
            return
        if not availability.available:
            host.show_unavailable(availability.missing)
            return
        try:
            assignments = self.panel.assignments()
        except Exception as exc:  # noqa: BLE001 - GUI boundary reports setup failures.
            host.show_error(str(exc))
            return
        try:
            self._generation = self.owner.request_start(WorkspaceId.CALL_BRIDGE)
        except SessionBusy as busy:
            host.show_error(str(busy))  # nothing was opened; the running session continues
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
            self.host.show_error(message or "Call bridge setup was cancelled")
            return
        self._begin_call_bridge(assignments, session)

    def _begin_call_bridge(self, assignments, session: SessionPair) -> None:
        bridge = self.host.bridge
        conversation = self.host.conversation
        try:
            lanes = CallBridgeLanes.from_session(session)
            recognizer = self.pipeline.speech_recognizer()
            translator = self.pipeline.text_translator()
            synthesizer = self.pipeline.voice_synthesizer()
            validate_voice_files = getattr(synthesizer, "validate_voice_files", None)
            if validate_voice_files is not None:
                validate_voice_files([lanes.local, lanes.remote])
            scheduler = InferenceScheduler(max_concurrent=2)
            outbound_playback = EndpointPlaybackStream(
                assignments[EndpointRole.CALL_MICROPHONE_RENDER]
            )
            inbound_playback = EndpointPlaybackStream(assignments[EndpointRole.LOCAL_HEADPHONES])
            outbound_lane = TranslationLane(
                LaneId.OUTBOUND,
                lanes.outbound,
                recognizer,
                translator,
                synthesizer,
                outbound_playback.play,
                scheduler,
                max_pending_age_ms=self.config.call_bridge.max_pending_age_ms,
                on_result=bridge.result.emit,
                on_event=bridge.call_bridge_event.emit,
            )
            inbound_lane = TranslationLane(
                LaneId.INBOUND,
                lanes.inbound,
                recognizer,
                translator,
                synthesizer,
                inbound_playback.play,
                scheduler,
                max_pending_age_ms=self.config.call_bridge.max_pending_age_ms,
                on_result=bridge.result.emit,
                on_event=bridge.call_bridge_event.emit,
            )
            outbound_capture = EndpointCaptureStream(
                assignments[EndpointRole.LOCAL_MICROPHONE],
                self.config.audio,
                outbound_lane.submit,
                on_level=lambda level: bridge.call_bridge_level.emit(
                    EndpointRole.LOCAL_MICROPHONE, level
                ),
                on_error=lambda message: bridge.call_bridge_capture_fault.emit(
                    EndpointRole.LOCAL_MICROPHONE, message
                ),
            )
            inbound_capture = EndpointCaptureStream(
                assignments[EndpointRole.CALL_SPEAKER_CAPTURE],
                self.config.audio,
                inbound_lane.submit,
                on_level=lambda level: bridge.call_bridge_level.emit(
                    EndpointRole.CALL_SPEAKER_CAPTURE, level
                ),
                on_error=lambda message: bridge.call_bridge_capture_fault.emit(
                    EndpointRole.CALL_SPEAKER_CAPTURE, message
                ),
            )
            controller = FullDuplexBridgeController(
                assignments,
                outbound_lane,
                inbound_lane,
                outbound_capture,
                inbound_capture,
                on_event=bridge.call_bridge_event.emit,
                endpoint_ports={
                    EndpointRole.LOCAL_MICROPHONE: outbound_capture,
                    EndpointRole.CALL_MICROPHONE_RENDER: outbound_playback,
                    EndpointRole.CALL_SPEAKER_CAPTURE: inbound_capture,
                    EndpointRole.LOCAL_HEADPHONES: inbound_playback,
                },
                session=session,
                catalog=self.pipeline.catalog,
            )
            self.controller = controller
            controller.start()
        except ModeUnavailableError as exc:
            self.controller = None
            self.owner.mark_idle(self._generation)
            conversation.refresh_availability()
            self.host.show_unavailable(exc.missing)
            return
        except Exception as exc:  # noqa: BLE001 - GUI boundary reports setup failures.
            self.controller = None
            self.owner.mark_idle(self._generation)
            conversation.refresh_availability()
            self.host.show_error(str(exc))
            return
        self.owner.mark_running(self._generation)
        self.panel.apply_to_config()
        self.panel.set_running(True)
        self._endpoint_monitor.start()
        conversation.start_button.setEnabled(False)
        conversation.set_session_controls_enabled(False)
        conversation.set_devices_enabled(False)
        self.host.statusBar().showMessage("Fail-closed full-duplex call bridge is active")

    @Slot()
    def stop_call_bridge(self) -> None:
        self._endpoint_monitor.stop()
        controller, self.controller = self.controller, None
        if controller is not None and not controller.stop(timeout=10.0):
            self.host.show_error("Call bridge workers did not stop within the shutdown contract")
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

    @Slot()
    def _reconcile_call_bridge_endpoints(self) -> None:
        if self.controller is None:
            return
        try:
            inventory = list_audio_endpoints()
            self.controller.reconcile_endpoints(inventory)
        except (RuntimeError, ValueError) as exc:
            self.host.statusBar().showMessage(f"Endpoint recovery check failed: {exc}", 10_000)

    @Slot(object, str)
    def _handle_call_bridge_capture_fault(self, role: EndpointRole, message: str) -> None:
        if self.controller is not None:
            self.controller.endpoint_lost(role)
        self.host.statusBar().showMessage(f"Call bridge capture muted: {message}", 15_000)

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
            self.host.statusBar().showMessage(
                f"Call bridge {event.lane_id.value if event.lane_id else ''} failed closed: "
                f"{event.category}",
                15_000,
            )
        elif event.kind is BridgeEventKind.DROPPED:
            self.host.statusBar().showMessage(
                f"Call bridge dropped stale work: {event.category}", 10_000
            )
        elif event.kind is BridgeEventKind.ENDPOINT:
            self.panel.set_state(
                BridgeState.DEGRADED if event.category == "endpoint_lost" else BridgeState.RUNNING,
                event.message,
            )

    @Slot(object, float)
    def _show_call_bridge_level(self, role: EndpointRole, level: float) -> None:
        self.panel.set_level(role, level)

    @Slot(object)
    def _run_call_bridge_route_test(self, role: EndpointRole) -> None:
        if self.controller is not None:
            self.host.show_error("Stop the call bridge before running an isolated route test")
            return
        try:
            assignments = self.panel.assignments()
            endpoint = assignments[role]
            lanes = CallBridgeLanes.from_session(self.session())
        except Exception as exc:  # noqa: BLE001 - UI validation boundary.
            self.host.show_error(str(exc))
            return
        # The call microphone carries the remote language, the headphones the local one.
        language = lanes.remote if role is EndpointRole.CALL_MICROPHONE_RENDER else lanes.local
        text = ROUTE_TEST_TEXT.get(language)
        if text is None:
            name = self.pipeline.registry.display_name(language)
            self.host.show_error(f"No route test phrase for {name}")
            return
        event = self.host.bridge.call_bridge_event

        def run_test() -> None:
            path = None
            try:
                # Constructed on demand; the voice loads on its first synthesis.
                synthesizer = self.pipeline.voice_synthesizer()
                path = synthesizer.synthesize(text, language)
                EndpointPlaybackStream(endpoint).play(path)
                event.emit(
                    BridgeEvent(None, BridgeEventKind.ENDPOINT, "route_test_passed", role.value)
                )
            except Exception as exc:  # noqa: BLE001 - diagnostic boundary.
                event.emit(
                    BridgeEvent(
                        None, BridgeEventKind.ERROR, type(exc).__name__, "route_test_failed"
                    )
                )
            finally:
                if path is not None:
                    path.unlink(missing_ok=True)

        threading.Thread(target=run_test, name="call-bridge-route-test", daemon=True).start()
