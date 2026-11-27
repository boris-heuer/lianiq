"""Notice producers of the Conversation workspace (CAP-0168 spec §2.3.4, WI-03).

Kept beside ``conversation.py`` so that module stays under the 32 KiB limit. It turns the
workspace's failures into notices (``notice_catalog``) and handles their actions:

- ``PipelineEvent``s from ``pipeline.py`` (queue overflow, dropped turns, playback failure)
  arrive through ``UiBridge.pipeline_event`` with the session generation of their start, so
  a late event of an older session is dropped;
- device loss (``DEVICE_MIC_LOST`` / ``DEVICE_SPEAKER_LOST``): ``microphone_lost`` stops the
  session (no auto-resume), ``speakers_lost`` keeps capture and turns spoken output off.
  The identity monitor of ``DeviceSetup`` (WI-04) detects the loss; a playback failure
  from the pipeline also counts as speakers lost (spec §2.2.3);
- **Reconnect** runs a full device refresh and reselects the same identity, only while no
  stream is open (``DEVICE_RECONNECT_AFTER_STOP`` otherwise); **Choose device** opens
  Settings › Audio devices with the selector of the flow focused;
- a failed speech synthesis (CAP-0167: the text stays, later turns are spoken). A failed
  transcript export is posted by ``PairedTranscriptView`` (paired-transcript WI-02).

The diagnostics log gets each turn's ID, languages and timings, never its text.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import QComboBox

from lianiq.call_bridge.contracts import EndpointFlow
from lianiq.domain import TranslationResult
from lianiq.pipeline import PipelineEvent, PipelineEventKind
from lianiq.ui import notice_catalog as catalog
from lianiq.ui import strings
from lianiq.ui.shell.workspaces import WorkspaceId

if TYPE_CHECKING:
    from lianiq.ui.workspaces.conversation import ConversationWorkspace

CONVERSATION = WorkspaceId.CONVERSATION
MICROPHONE, SPEAKERS = strings.NOTICE_MICROPHONE, strings.NOTICE_SPEAKERS
CAPTURE, RENDER = EndpointFlow.CAPTURE, EndpointFlow.RENDER


class ConversationNotices:
    def __init__(self, workspace: ConversationWorkspace) -> None:
        self.workspace = workspace
        self.host = workspace.host

    def where(self, language=None) -> str:
        """The notice source: "Conversation · <pair>", or the turn's language when known."""
        if language is not None:
            return catalog.source(CONVERSATION, self.host.pipeline.registry.display_name(language))
        pair = self.workspace.current_pair()
        return catalog.source(
            CONVERSATION, None if pair is None else self.workspace.pairs.pair_name(pair)
        )

    def post(self, notice) -> bool:
        return self.host.post_notice(notice)

    # Session start --------------------------------------------------------------------------

    def model_failed(self, reason: str) -> None:
        self.post(
            catalog.model_failed(CONVERSATION, reason, self.where(), self.workspace.start_listening)
        )

    def start_failed(self, reason: str) -> None:
        self.post(
            catalog.start_failed(CONVERSATION, reason, self.where(), self.workspace.start_listening)
        )

    def running(self) -> None:
        """The session runs: its start-related notices are resolved."""
        self.host.resolve_notices(catalog.keys_resolved_by_start(CONVERSATION))

    def availability(self, available: bool) -> None:
        """Resolve the unavailable notice once the selected mode is available again."""
        if available:
            self.host.notices.resolve(catalog.unavailable_key(CONVERSATION))

    def stopped(self, discarded: int) -> None:
        if discarded:
            self.post(catalog.held_discarded(discarded, self.where()))

    def pair_locked(self) -> None:
        self.post(catalog.pair_locked(self.where()))

    def direction(self, missing_text: str | None) -> None:
        """**Switch direction** refused (``missing_text``), or a successful switch."""
        if missing_text:
            self.post(catalog.direction_unavailable(missing_text, self.where()))
        else:
            self.host.notices.resolve(catalog.DIRECTION_UNAVAILABLE)

    # Pipeline notice events -----------------------------------------------------------------

    def pipeline_event(self, event: PipelineEvent, generation: int) -> None:
        self.host.diagnostics.record(
            "pipeline", f"{event.kind.value} x{event.count}: {event.message}"
        )
        where = self.where(event.language)
        if event.kind is PipelineEventKind.QUEUE_OVERFLOW:
            self.post(catalog.queue_overflow(where, generation))
        elif event.kind is PipelineEventKind.TURNS_DROPPED:
            self.post(catalog.turns_dropped(event.count, where, generation))
        elif event.kind is PipelineEventKind.SYNTHESIS_FAILED and event.language is not None:
            name = self.host.pipeline.registry.display_name(event.language)
            self.post(catalog.synthesis_failed(name, where, generation))
        elif event.kind is PipelineEventKind.PLAYBACK_FAILED:
            self.speakers_lost(generation=generation)

    def record_result(self, result: TranslationResult) -> None:
        self.host.diagnostics.record(
            "turn",
            f"{result.turn_id} {result.source_language}>{result.target_language} "
            f"{result.total_seconds:.2f} s",
        )

    # Devices --------------------------------------------------------------------------------

    def microphone_lost(self, name: str | None = None, generation: int | None = None) -> None:
        """The microphone faulted or left the inventory: stop, keep the transcript."""
        workspace = self.workspace
        name = name or self.host.device_setup.device_name(CAPTURE)
        if self.host.session_owner.active is CONVERSATION:
            self.host.session_owner.stop()
        else:
            workspace.stop_listening()
        self.post(
            catalog.microphone_lost(
                name,
                self.where(),
                lambda: self.reconnect(MICROPHONE),
                self.can_reconnect,
                lambda: self.choose_device(MICROPHONE),
                generation,
            )
        )

    def speakers_lost(self, name: str | None = None, generation: int | None = None) -> None:
        """The speakers failed or left: capture continues, spoken output is off."""
        name = name or self.host.device_setup.device_name(RENDER)
        self.host.pipeline.set_spoken_languages(frozenset())
        self.workspace.refresh_playback()  # nothing is spoken or replayed any more
        self.post(
            catalog.speakers_lost(
                name,
                self.where(),
                lambda: self.reconnect(SPEAKERS),
                self.can_reconnect,
                lambda: self.choose_device(SPEAKERS),
                generation,
            )
        )

    def can_reconnect(self) -> bool:
        """A full refresh only runs while no stream is open (contract §4)."""
        return not self.host.session_locked()

    def reconnect(self, flow: str) -> None:
        """Full refresh; the same identity is reselected; resolve the notice if it is back."""
        if not self.can_reconnect():
            return
        setup = self.host.device_setup
        if not setup.refresh():
            return
        back = setup.resolved(CAPTURE if flow == MICROPHONE else RENDER).ready
        key = catalog.MICROPHONE_LOST if flow == MICROPHONE else catalog.SPEAKERS_LOST
        if back:
            self.host.notices.resolve(key)
        else:
            notice = self.host.notices.get(key)
            if notice is not None:
                self.post(notice)  # still missing: the same notice, one more repeat

    def choose_device(self, flow: str) -> None:
        """Open Settings › Audio devices with the selector of ``flow`` focused."""
        self.host.show_workspace(WorkspaceId.SETTINGS)
        setup = self.host.device_setup
        combo: QComboBox = setup.input_combo if flow == MICROPHONE else setup.output_combo
        combo.setFocus()
