"""Per-turn **Replay** for a ``TranscriptHost`` (paired-transcript spec §2.2.2, §3.3).

``ReplayHost`` gives Conversation and Listen the replay members of ``TranscriptHost``; both
go through the app's one ``SpokenOutput`` (``host.pipeline.spoken``). **Replay** is allowed
iff nothing plays, no other usage holds the session, the row's target voice is ready
(``voice_status`` with ``outputs={target}``, as CAP-0167 computes it) and the speakers are
available; otherwise the tooltip names the reason. A synthesis or playback failure is a
notice of the workspace that started the replay; it never changes the spoken plan. An idle
replay takes no session claim: every session Start calls ``end_playback`` first.
"""

from __future__ import annotations

import threading

from PySide6.QtCore import QObject, Signal, Slot

from lianiq.call_bridge.contracts import EndpointFlow
from lianiq.conversation.spoken_output import PlaybackState, VoiceState, voice_status
from lianiq.pipeline_types import PipelineEvent, PipelineEventKind
from lianiq.transcript.turns import Turn
from lianiq.ui import notice_catalog as catalog
from lianiq.ui import strings
from lianiq.ui.notice_catalog_base import _notice
from lianiq.ui.notices import Notice, Severity
from lianiq.ui.shell.workspaces import WorkspaceId, session_busy_message

CONVERSATION = WorkspaceId.CONVERSATION


def end_playback(window, mode: WorkspaceId) -> None:
    """A session Start of ``mode`` ends a playback first (only when its start is not refused)."""
    spoken = getattr(window.pipeline, "spoken", None)
    if spoken is not None and window.session_owner.busy_for(mode) is None:
        spoken.stop_playback()


def replay_failed(workspace: WorkspaceId, event: PipelineEvent, name: str, where: str) -> Notice:
    """The CAP-0167 synthesis notice, or the playback-failed notice; no turn text."""
    if event.kind is PipelineEventKind.SYNTHESIS_FAILED:
        if workspace is CONVERSATION:
            return catalog.synthesis_failed(name, where)
        title, detail = strings.VOICE_SYNTH_FAILED.format(language=name), strings.DETAIL_VOICE
    else:
        title = strings.TEXT_PLAYBACK_FAILED.format(reason=strings.TEXT_REASON_DEVICE)
        detail = strings.DETAIL_DEVICE
    key = f"{workspace.value}.replay-failed"
    return _notice(
        key, Severity.WARNING, title, detail, where, strings.CONTINUES_NOTHING, workspace
    )


class TranscriptReplay(QObject):
    """One workspace's replay state; signals carry speaking-thread changes to the GUI."""

    changed = Signal()
    failed = Signal(object)

    def __init__(self, host) -> None:
        super().__init__()
        self.host = host  # the workspace (``TranscriptHost``)
        self.thread: threading.Thread | None = None
        self.requested = False  # between the click and ``replay_turn`` returning
        self.changed.connect(self._refresh)
        self.failed.connect(self._failed)
        self._attached = None
        host.host.session_owner.subscribe(lambda *_: self.changed.emit())

    @property
    def window(self):
        return self.host.host

    def spoken(self):
        return getattr(self.window.pipeline, "spoken", None)

    def attach(self, spoken) -> None:
        """Refresh the view on every playback state change (any page's playback)."""
        if spoken is not None and spoken is not self._attached:
            self._attached = spoken
            spoken.subscribe(lambda _state: self.changed.emit())

    def owns(self, replay: threading.Thread | None) -> bool:
        """``replay`` was started from this page (read on the speaking thread)."""
        return self.requested or (replay is not None and replay is self.thread)

    def block(self, turn: Turn) -> str | None:
        """``None`` when **Replay** of ``turn`` is allowed, else its tooltip (spec §2.2.2)."""
        spoken = self.spoken()
        if spoken is None or spoken.state is not PlaybackState.IDLE or spoken.active_replay:
            return ""  # something plays: disabled on every row
        window = self.window
        active = window.session_owner.active
        if active is not None and active is not self.host.workspace:
            return session_busy_message(active)
        registry, target = window.pipeline.registry, turn.target_language
        status = voice_status(
            target,
            catalog=window.pipeline.catalog,
            config=window.config,
            registry=registry,
            outputs=frozenset({target}),
            packs=getattr(getattr(window, "language_packs", None), "packs", None),
        )
        if status.state is not VoiceState.READY:
            return strings.TRANSCRIPT_REPLAY_NO_VOICE.format(language=registry.display_name(target))
        if not window.device_readiness().playback:
            return strings.TRANSCRIPT_REPLAY_NO_SPEAKERS
        return None

    def replay(self, turn: Turn) -> None:
        spoken = self.spoken()
        if spoken is None or turn.result is None or self.block(turn) is not None:
            return
        endpoint = self.window.device_setup.resolved(EndpointFlow.RENDER).endpoint
        device = None if endpoint is None else endpoint.runtime_index
        self.requested = True
        try:
            self.thread = spoken.replay_turn(turn.result, device, self.failed.emit)
        finally:
            self.requested = False

    def stop(self) -> None:
        spoken = self.spoken()
        if spoken is not None:
            spoken.stop_playback()

    def playing(self) -> bool:
        """A playback started from this view synthesizes or plays."""
        spoken = self.spoken()
        replay = None if spoken is None else spoken.active_replay
        return replay is not None and replay is self.thread

    @Slot()
    def _refresh(self) -> None:
        view = getattr(self.host, "paired_view", None)
        if view is not None:
            view.refresh()

    @Slot(object)
    def _failed(self, event: PipelineEvent) -> None:
        name = self.window.pipeline.registry.display_name(event.language) if event.language else ""
        where = catalog.source(self.host.workspace, name or None)
        self.host.post_notice(replay_failed(self.host.workspace, event, name, where))


class ReplayHost:
    """The ``TranscriptHost`` replay members of a workspace (``host`` is the ``MainWindow``)."""

    _replayer: TranscriptReplay | None = None

    @property
    def replayer(self) -> TranscriptReplay:
        if self._replayer is None:
            self._replayer = TranscriptReplay(self)
        return self._replayer

    def replay_block(self, turn: Turn) -> str | None:
        return self.replayer.block(turn)

    def replay(self, turn: Turn) -> None:
        self.replayer.replay(turn)

    def stop_playback(self) -> None:
        self.replayer.stop()

    def playing(self) -> bool:
        return self.replayer.playing()
