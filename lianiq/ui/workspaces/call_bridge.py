"""The Call Bridge workspace: lanes, endpoints, route tests and recovery (CAP-0168 WI-01).

Moved behaviour-neutrally out of ``ui/main_window.py``. The workspace owns the
``CallBridgePanel`` and the running ``FullDuplexBridgeController``; ``MainWindow`` provides
the shared status bar, session lock and model warm-up.

CAP-0168 WI-02: the panel is the workspace's own page (sidebar entry *Call Bridge*,
"Experimental") with its explicit endpoint selectors only. A start goes through
``ActiveSessionOwner.request_start``: while the conversation holds the session it is refused
with ``SESSION_BUSY`` and opens no stream, and the panel's **Start** is disabled with that
tooltip. A running conversation is never stopped by a Call Bridge start any more.

CAP-0168 WI-03: failures and ``BridgeEvent`` errors are notices in the Call Bridge workspace
(``notice_catalog``), naming the lane and its language; the status bar shows progress only.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QTimer, Slot

from lianiq.audio.capture_stream import EndpointCaptureStream
from lianiq.audio.endpoints import list_audio_endpoints
from lianiq.audio.playback_stream import EndpointPlaybackStream
from lianiq.call_bridge.contracts import (
    BridgeEvent,
    BridgeEventKind,
    CallBridgeLanes,
    EndpointRole,
    LaneId,
)
from lianiq.call_bridge.controller import FullDuplexBridgeController
from lianiq.call_bridge.inference_scheduler import InferenceScheduler
from lianiq.call_bridge.translation_lane import TranslationLane
from lianiq.languages.errors import ModeUnavailableError
from lianiq.languages.modes import SessionPair
from lianiq.languages.registry import LanguageId
from lianiq.ui import notice_catalog as catalog
from lianiq.ui.shell.workspaces import WorkspaceId

# CAP-0168 file-size split: the panel, Start/Stop, lane names and event handling moved to
# ``call_bridge_lifecycle.py``. Stream, endpoint and controller construction stays here, so
# the names tests and scripts patch on this module are still looked up here.
from lianiq.ui.workspaces.call_bridge_lifecycle import CALL_BRIDGE, CallBridgeLifecycle

if TYPE_CHECKING:
    from lianiq.ui.main_window import MainWindow

# Route-test phrases per language (functional data). The Call Bridge lanes themselves come
# from the session pair and ``call_bridge.local_language`` (``CallBridgeLanes``).
ROUTE_TEST_TEXT = {LanguageId("de"): "Kopfhörer-Test.", LanguageId("zh-Hans"): "通话麦克风测试。"}


class CallBridgeWorkspace(CallBridgeLifecycle, QObject):
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

    def load_endpoints(self) -> None:
        try:
            inventory = list_audio_endpoints()
        except (RuntimeError, ValueError) as exc:
            self.panel.set_endpoints([])
            self.panel.set_state("unavailable", str(exc))
        else:
            self.panel.set_endpoints(inventory.endpoints)

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
            self.host.show_unavailable(exc.missing, CALL_BRIDGE)
            return
        except Exception as exc:  # noqa: BLE001 - GUI boundary reports setup failures.
            self.controller = None
            self.owner.mark_idle(self._generation)
            conversation.refresh_availability()
            self.host.post_notice(
                catalog.start_failed(
                    CALL_BRIDGE, str(exc), self._lane_source(None), self.start_call_bridge
                )
            )
            return
        self.owner.mark_running(self._generation)
        self.host.resolve_notices(catalog.keys_resolved_by_start(CALL_BRIDGE))
        for role, endpoint in assignments.items():  # redacted on Copy/Export
            self.host.diagnostics.record("call-bridge", f"{role.value}: {endpoint.endpoint_id}")
        self.panel.apply_to_config()
        self.panel.set_running(True)
        self._endpoint_monitor.start()
        conversation.start_button.setEnabled(False)
        conversation.set_session_controls_enabled(False)
        conversation.set_devices_enabled(False)
        self.host.statusBar().showMessage("Fail-closed full-duplex call bridge is active")

    @Slot()
    def _reconcile_call_bridge_endpoints(self) -> None:
        if self.controller is None:
            return
        try:
            inventory = list_audio_endpoints()
            self.controller.reconcile_endpoints(inventory)
        except (RuntimeError, ValueError) as exc:
            self.host.post_notice(catalog.bridge_recovery_failed(str(exc), self._lane_source(None)))

    @Slot(object)
    def _run_call_bridge_route_test(self, role: EndpointRole) -> None:
        if self.controller is not None:
            self._error("Stop the call bridge before running an isolated route test")
            return
        try:
            assignments = self.panel.assignments()
            endpoint = assignments[role]
            lanes = CallBridgeLanes.from_session(self.session())
        except Exception as exc:  # noqa: BLE001 - UI validation boundary.
            self._error(str(exc))
            return
        # The call microphone carries the remote language, the headphones the local one.
        language = lanes.remote if role is EndpointRole.CALL_MICROPHONE_RENDER else lanes.local
        text = ROUTE_TEST_TEXT.get(language)
        if text is None:
            name = self.pipeline.registry.display_name(language)
            self._error(f"No route test phrase for {name}")
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
