"""Readiness and route tests of ``CallBridgeWorkspace`` (CAP-0166 WI-02, spec §2.2, §3.2).

``readiness_reasons`` feeds the panel's ``evaluate_readiness`` call with the session, the
requirement row 7 and the registry. A route test plays the route-test phrase on one path's
playback endpoint only: the remote language into the call microphone cable (*You → call*),
the local language into the headphones (*Call → you*). Its row moves *Playing test…* →
question → result in the workspace's ``RouteTestBook``; a test never touches the controller
or the session owner, and its result arrives on its own signal, never as a ``BridgeEvent``.
"""

from __future__ import annotations

import threading

from PySide6.QtCore import QObject, Signal, Slot

from lianiq.call_bridge.contracts import CallBridgeLanes, EndpointRole, LaneId
from lianiq.call_bridge.controller import check_call_bridge
from lianiq.call_bridge.readiness import BlockingReason, ReadinessCode, evaluate_readiness
from lianiq.call_bridge.route_tests import PATH_ROLES, RouteTestBook, RouteTestState
from lianiq.ui import strings_call_bridge as s
from lianiq.ui.shell.session_owner import SessionState
from lianiq.ui.shell.workspaces import WorkspaceId

_IDLE = frozenset(
    {
        RouteTestState.NOT_TESTED,
        RouteTestState.PASSED,
        RouteTestState.FAILED,
        RouteTestState.CANCELLED,
        RouteTestState.PLAY_ERROR,
    }
)


class RouteTestRelay(QObject):
    """Worker-thread results, delivered on the GUI thread."""

    finished = Signal(object, int, str)  # path, test token, error ("" when it played)
    clipping = Signal(object)  # the capture ``EndpointRole`` that clipped


class CallBridgeSetup:
    """``CallBridgeWorkspace`` mixin: readiness, route-test flow and level clipping."""

    def init_setup(self) -> None:
        self.route_tests = RouteTestBook()
        self._test_tokens = dict.fromkeys(LaneId, 0)
        self.relay = RouteTestRelay(self)
        self.relay.finished.connect(self._route_test_finished)
        self.relay.clipping.connect(self._show_clipping)
        # Pack, voice and model changes refresh the conversation's availability.
        self.host.conversation.voice_rows_changed.connect(self.refresh_readiness)

    def connect_setup(self, panel) -> None:
        panel.route_test_requested.connect(self._run_call_bridge_route_test)
        panel.route_test_cancelled.connect(self._cancel_route_test)
        panel.route_test_answered.connect(self._answer_route_test)
        panel.selection_changed.connect(self.show_route_tests)

    def readiness_reasons(
        self, assignments, inventory, *, models_ready, busy_reason, running
    ) -> tuple[BlockingReason, ...]:
        try:
            session = self.session()
            availability = check_call_bridge(session, self.pipeline.catalog, EndpointRole)
        except Exception as exc:  # noqa: BLE001 - an invalid setting blocks Start, named.
            return (BlockingReason(ReadinessCode.MODE_UNAVAILABLE, None, str(exc)),)
        testing = (
            (BlockingReason(ReadinessCode.RUNNING, None, s.CB_R_TESTING),)
            if self.route_test_active()
            else ()
        )
        return testing + evaluate_readiness(
            assignments,
            inventory,
            session,
            availability,
            models_ready=models_ready,
            busy_reason=busy_reason,
            running=running,
            registry=self.pipeline.registry,
        )

    def route_test_active(self) -> bool:
        """A route test plays or waits for its answer: Start stays disabled (WI-02 advisory)."""
        book = getattr(self, "route_tests", None)
        return book is not None and any(book.state(path) not in _IDLE for path in LaneId)

    @Slot()
    def refresh_readiness(self) -> None:
        # Only while the page is shown: a hidden page re-evaluates when it is shown again,
        # so frequent availability refreshes never relayout the other workspaces.
        panel = getattr(self, "panel", None)
        if panel is not None and panel.isVisible():
            panel.refresh()

    def _test_language(self, path: LaneId):
        lanes = CallBridgeLanes.from_session(self.session())
        return lanes.remote if path is LaneId.OUTBOUND else lanes.local

    def _test_blocked(self, path: LaneId) -> str:
        """Why **Test** of ``path`` is disabled; ``""`` when it can play."""
        owner = self.owner
        if owner.active is WorkspaceId.CALL_BRIDGE and owner.state is not SessionState.IDLE:
            return s.CB_TEST_RUNNING
        try:
            language = self._test_language(path)
        except Exception as exc:  # noqa: BLE001 - an invalid setting is named on Start.
            return str(exc)
        if self.route_test_phrase(language) is None:
            name = self.pipeline.registry.display_name(language)
            return s.CB_TEST_NO_PHRASE.format(language=name)
        role = PATH_ROLES[path][1]
        if self.panel.endpoint(role) is None:
            return s.CB_R_SELECT.format(role=s.CB_ROLE_LABELS[role])
        return ""

    @Slot()
    def show_route_tests(self) -> None:
        """Reset a path whose devices, pair or local language changed; redraw both rows."""
        try:
            session = self.session()
            pair, local = session.pair, session.local_language
        except Exception:  # noqa: BLE001 - an invalid setting: fingerprint the raw values.
            pair = tuple(self.config.languages.pair)
            local = self.config.call_bridge.local_language
        for path in self.route_tests.update(self.panel.selected_ids(), pair, local):
            self._test_tokens[path] += 1  # a playing test of that path no longer counts
        for path in LaneId:
            self._show_test(path)

    def _show_test(self, path: LaneId) -> None:
        book = self.route_tests
        self.panel.set_route_test(
            path, book.state(path), book.detail(path), self._test_blocked(path)
        )

    def _set_test(self, path: LaneId, state: RouteTestState, detail: str = "") -> None:
        self.route_tests.set(path, state, detail)
        self._show_test(path)
        self.panel.refresh()  # Start follows whether a test is active

    @Slot(object)
    def _run_call_bridge_route_test(self, path: LaneId) -> None:
        if self._test_blocked(path) or self.route_tests.state(path) not in _IDLE:
            return
        endpoint = self.panel.endpoint(PATH_ROLES[path][1])
        language = self._test_language(path)
        text = self.route_test_phrase(language)
        self._test_tokens[path] += 1
        token = self._test_tokens[path]
        self._set_test(path, RouteTestState.PLAYING)
        pipeline, finished = self.pipeline, self.relay.finished

        def run_test() -> None:
            audio, error = None, ""
            try:
                # Constructed on demand; the voice loads on its first synthesis.
                audio = pipeline.voice_synthesizer().synthesize(text, language)
                self.play_route_test(endpoint, audio)
            except Exception as exc:  # noqa: BLE001 - shown in the test row.
                error = str(exc) or type(exc).__name__
            finally:
                if audio is not None:
                    audio.unlink(missing_ok=True)
            finished.emit(path, token, error)

        threading.Thread(target=run_test, name="call-bridge-route-test", daemon=True).start()

    @Slot(object, int, str)
    def _route_test_finished(self, path: LaneId, token: int, error: str) -> None:
        if token != self._test_tokens[path]:
            return  # cancelled or reset meanwhile
        if self.route_tests.state(path) is RouteTestState.PLAYING:
            if error:
                self._set_test(path, RouteTestState.PLAY_ERROR, error)
            else:
                self._set_test(path, RouteTestState.AWAITING_ANSWER)

    @Slot(object)
    def _cancel_route_test(self, path: LaneId) -> None:
        if self.route_tests.state(path) is RouteTestState.PLAYING:
            self._test_tokens[path] += 1
            self._set_test(path, RouteTestState.CANCELLED)

    @Slot(object, bool)
    def _answer_route_test(self, path: LaneId, heard: bool) -> None:
        if self.route_tests.state(path) is not RouteTestState.AWAITING_ANSWER:
            return
        if heard:
            self._set_test(path, RouteTestState.PASSED)
        else:
            setting = s.CB_SETTING_OUT if path is LaneId.OUTBOUND else s.CB_SETTING_IN
            self._set_test(path, RouteTestState.FAILED, setting)

    @Slot(object)
    def _show_clipping(self, role: EndpointRole) -> None:
        self.panel.set_clipping(role)
