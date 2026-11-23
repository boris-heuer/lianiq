"""Microphone loss on the Listen page (CAP-0170 WI-05, spec §2.2.3, AC-14).

``ListenWorkspace`` base (file-size split). While a session runs, the CAP-0168 2 s identity
monitor calls ``check_microphone``: a microphone whose identity left the inventory, or whose
stream PortAudio stopped, is lost and the controller stops by its stop policy (a capture
``on_error`` reaches the controller directly). The blocking ``listen.microphone-lost`` notice
offers **Reconnect** (a full refresh; resolved only when the same identity is back) and
**Choose device** (focus *Microphone*). Another microphone is never chosen; capture restarts
only on Start, which also resolves the notice.
"""

from __future__ import annotations

from lianiq.listen.lifecycle import ListenPhase
from lianiq.ui import notice_catalog as catalog
from lianiq.ui import notice_catalog_listen as listen_notices
from lianiq.ui.notice_catalog_base import LISTEN_MIC_LOST
from lianiq.ui.shell.workspaces import WorkspaceId

RUNNING = (ListenPhase.LOADING, ListenPhase.LISTENING)


class ListenDevices:
    """Loss detection of the session microphone and the notice's two actions."""

    _opened = None  # the ResolvedDevice the running session opened
    _lost_id: str | None = None  # the endpoint the live loss notice names
    _stream = None  # the last MicrophoneCapture built (``stream_failed``)

    def remember_microphone(self) -> None:
        self._opened = self.microphone()

    def check_microphone(self) -> None:
        """``DeviceWatch`` tick: report a lost session microphone to the controller once."""
        opened = self._opened
        if self.controller.phase not in RUNNING or opened is None:
            return
        failed = bool(getattr(self._stream, "stream_failed", False))
        endpoint = opened.endpoint
        gone = endpoint is not None and not self.host.device_setup.state.present(
            endpoint.endpoint_id
        )
        if failed or gone:
            self.controller.microphone_lost(opened.label)

    def microphone_lost(self, device_name: str, generation: int) -> None:
        opened = self._opened
        endpoint = None if opened is None else opened.endpoint
        self._lost_id = None if endpoint is None else endpoint.endpoint_id
        # The device itself, not the selector label ("Follow Windows default (now: …)").
        name = device_name if endpoint is None else endpoint.display_name
        notice = listen_notices.microphone_lost(
            name,
            catalog.source(WorkspaceId.LISTEN),
            self.reconnect_microphone,
            self.can_reconnect,
            self.choose_microphone,
            generation,
        )
        self.host.post_notice(notice)

    def can_reconnect(self) -> bool:
        """A full refresh only runs while no stream is open (CAP-0168 contract §4)."""
        return not self.host.session_locked()

    def reconnect_microphone(self) -> None:
        if not self.can_reconnect() or not self.host.device_setup.refresh():
            return
        self.refresh()  # reloads *Microphone*; the saved choice is kept, never replaced
        resolved = self.microphone()
        endpoint = resolved.endpoint
        same = endpoint is not None and endpoint.endpoint_id == self._lost_id
        if resolved.ready and (self._lost_id is None or same):
            self.host.notices.resolve(LISTEN_MIC_LOST)
        elif (notice := self.host.notices.get(LISTEN_MIC_LOST)) is not None:
            self.host.post_notice(notice)  # still missing: the same notice, one more repeat

    def choose_microphone(self) -> None:
        self.host.show_workspace(WorkspaceId.LISTEN)
        self.microphone_combo.setFocus()
