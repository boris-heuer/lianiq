"""Device loss, the identity monitor and the no-signal warning of ``DeviceSetup`` (WI-04).

CAP-0168 spec §2.2.3, §2.3.5 and contract §4 "Refresh strategy":

- While any stream is open, a 2 s monitor compares the native identities (no PortAudio
  refresh): a change is reported once as ``DEVICE_CHANGED`` and the full refresh runs when
  the last stream closes. A session microphone whose identity disappears, or whose stream
  PortAudio stopped, is lost (the session stops); session speakers whose identity
  disappears are lost (capture continues text-only).
- The Conversation level meter turns into the ``DEVICE_NO_SIGNAL`` warning after 10 s of
  silence; while spoken output plays, capture is muted and sends no level, so that time
  never counts as silence.
"""

from __future__ import annotations

from PySide6.QtCore import QTimer, Slot

from lianiq.audio.device_selection import display_labels
from lianiq.audio.device_state import MONITOR_INTERVAL_MS
from lianiq.call_bridge.contracts import EndpointFlow
from lianiq.ui import notice_catalog as catalog
from lianiq.ui import strings
from lianiq.ui.shell.session_owner import SessionState

CAPTURE, RENDER = EndpointFlow.CAPTURE, EndpointFlow.RENDER
FLOW_NAMES = {CAPTURE: strings.NOTICE_MICROPHONE, RENDER: strings.NOTICE_SPEAKERS}
NO_SIGNAL_LEVEL = 0.02  # meter fraction below which a block counts as silence
CONVERSATION_SILENCE_SECONDS = 10.0
LEVEL_GAP_SECONDS = 1.0  # a longer pause between levels: capture was muted


class DeviceWatch:
    def init_watch(self) -> None:
        self.monitor = QTimer(self)
        self.monitor.setInterval(MONITOR_INTERVAL_MS)
        self.monitor.timeout.connect(self.monitor_tick)
        self._last_level_at: float | None = None
        self._last_signal_at = 0.0
        self.host.session_owner.subscribe(self._owner_changed)
        self.host.bridge.level.connect(self.conversation_level)

    def where(self) -> str:
        return self.host.conversation.notices.where()

    def choose(self, flow: EndpointFlow):
        return lambda: self.host.conversation.notices.choose_device(FLOW_NAMES[flow])

    def device_name(self, flow: EndpointFlow) -> str:
        """The label of the session's (or else the selected) device of ``flow``; no ID."""
        resolved = self.active.get(flow) or self.resolved(flow)
        if resolved.endpoint is None:
            return resolved.choice.display_name or strings.DEVICE_SAVED
        labels = display_labels(self.state.inventory.endpoints)
        return labels.get(resolved.endpoint.endpoint_id, resolved.endpoint.display_name)

    def session_started(self) -> None:
        """The conversation opened its devices: remember them for loss detection."""
        self.active = {flow: self.resolved(flow) for flow in (CAPTURE, RENDER)}
        self._last_level_at = None

    def _owner_changed(self, state: SessionState, _active) -> None:
        idle = state is SessionState.IDLE
        self.set_tests_enabled(idle)
        if not idle:
            self.monitor.start()
            return
        self.active = {}
        self._last_level_at = None
        self.host.notices.resolve(catalog.NO_SIGNAL)
        # After the stop has finished (the stopping mode may still hold its streams).
        QTimer.singleShot(0, self.streams_closed)

    @Slot()
    def streams_closed(self) -> None:
        """No session and no test: stop the monitor, run a pending full refresh."""
        if self.streams_open():
            return
        self.monitor.stop()
        if self.state.after_stop() is not None:
            self.after_full_refresh()

    @Slot()
    def monitor_tick(self) -> None:
        change = self.state.check_identities()
        if not change.is_empty():
            self.host.post_notice(catalog.devices_changed(change.summary(), self.where()))
        conversation = self.host.conversation
        if not conversation.capture.running:
            return
        microphone = self.active.get(CAPTURE)
        if conversation.capture.stream_failed or not self._present(microphone):
            conversation.notices.microphone_lost(self.device_name(CAPTURE))
            return
        if self.host.pipeline.voice_output and not self._present(self.active.get(RENDER)):
            conversation.notices.speakers_lost(self.device_name(RENDER))

    def _present(self, resolved) -> bool:
        if resolved is None or resolved.endpoint is None:
            return True
        return self.state.present(resolved.endpoint.endpoint_id)

    @Slot(float)
    def conversation_level(self, level: float) -> None:
        if not self.host.conversation.capture.running:
            return
        now = self.clock()
        if self._last_level_at is None or now - self._last_level_at > LEVEL_GAP_SECONDS:
            self._last_signal_at = now  # the first level, or the first after muted playback
        self._last_level_at = now
        if level >= NO_SIGNAL_LEVEL:
            self._last_signal_at = now
            self.host.notices.resolve(catalog.NO_SIGNAL)
        elif now - self._last_signal_at >= CONVERSATION_SILENCE_SECONDS:
            if self.host.notices.get(catalog.NO_SIGNAL) is None:
                self.host.post_notice(
                    catalog.no_signal(self.device_name(CAPTURE), self.where(), self.choose(CAPTURE))
                )
