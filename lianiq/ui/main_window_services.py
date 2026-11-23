"""Session, notice and warm-up services ``MainWindow`` shares (CAP-0168 file-size split)."""

from __future__ import annotations

import threading

from PySide6.QtCore import Signal

from lianiq.languages.capabilities import CapabilityCatalog, ReadinessProbe
from lianiq.languages.modes import SessionPair
from lianiq.languages.requirements import ModeAvailability, describe
from lianiq.packs.catalog import PackKind
from lianiq.packs.errors import ManifestError
from lianiq.packs.manifest import Manifest
from lianiq.packs.protection import ActiveUsageTracker
from lianiq.packs.state import readiness_pack_files
from lianiq.ui import notice_catalog as catalog
from lianiq.ui import strings
from lianiq.ui.notices import Notice
from lianiq.ui.shell.session_owner import SessionState
from lianiq.ui.shell.workspaces import WorkspaceId
from lianiq.ui.workspaces.text_translation import TextTranslationWorkspace

# The pipeline adapter that loaded the models of a pack kind (spec §3.4).
ADAPTERS = {
    PackKind.RECOGNITION: "recognizer",
    PackKind.TRANSLATION: "translator",
    PackKind.VOICE: "synthesizer",
}


class MainWindowServices:
    """``MainWindow`` base: the session lock, notices and model warm-up of the workspaces."""

    def _session_changed(self, state: SessionState, active: WorkspaceId | None) -> None:
        self.session_strip.show_state(state, active)
        self.navigation.set_session_owner(None if state is SessionState.IDLE else active)
        self.diagnostics.record("session", f"{active.value if active else '-'} {state.value}")
        if state is SessionState.IDLE:
            # A refused start may be retried now; the pair is no longer locked.
            for workspace in self.workspace_pages:
                self.notices.resolve(catalog.busy_key(workspace))
            self.notices.resolve(catalog.PAIR_LOCKED)
        for banner in self.banners.values():  # e.g. Reconnect is available after Stop
            banner.update_action_states()
        if state is SessionState.IDLE and getattr(self, "_readiness_stale", False):
            self.refresh_readiness()

    @property
    def usage_tracker(self) -> ActiveUsageTracker:
        """The one tracker of the session's packs (contract.md §8), built on first use."""
        tracker = getattr(self, "_usage_tracker", None)
        if tracker is None:
            tracker = self._usage_tracker = ActiveUsageTracker(self.session_owner)
        return tracker

    def refresh_readiness(self, kind: PackKind | None = None) -> None:
        """After a pack job (spec §3.4): new readiness in every workspace without a restart.

        ``kind`` names the pack kind whose files the job changed; its cached adapter is
        dropped. The rebuilt probe also checks every listed pack file (C §4), as the page
        does. While a session runs, the refresh waits until the session is idle.
        """
        stale = getattr(self, "_stale_adapters", set())
        self._stale_adapters = stale | ({ADAPTERS[kind]} if kind is not None else set())
        self._readiness_stale = True
        if self.session_owner.state is not SessionState.IDLE:
            return
        self._readiness_stale = False
        self.pipeline.drop_adapters(self._stale_adapters)
        self._stale_adapters = set()
        old = self.pipeline.catalog.probe
        old.invalidate()  # a holder of the old catalog re-reads the files too
        probe = ReadinessProbe(old.root, old.manifest_path, pack_files=self._pack_files(old))
        rebuilt = CapabilityCatalog.from_config(self.config, self.pipeline.registry, probe)
        self.pipeline.catalog = rebuilt
        self.conversation.session_controller.catalog = rebuilt
        self.conversation.populate_pairs()
        self.conversation.refresh_availability()
        self.meeting.refresh()
        text = getattr(self, "text_translation", None)
        if text is not None:  # the next Translate and Play use the rebuilt adapters
            text.controller.refresh()
        if self.current_workspace() is WorkspaceId.SETTINGS:
            self.settings.refresh()

    def _pack_files(self, probe: ReadinessProbe):
        try:
            manifest = Manifest.read(probe.manifest_path)
        except ManifestError:
            manifest = Manifest()
        try:
            packs = self.language_packs.packs
            return readiness_pack_files(packs, manifest, self.config, probe.root)
        except OSError:  # the CAP-0169 rules alone, as before any pack job
            return None

    def build_text_translation_page(self):
        """The Text translation workspace (CAP-0172); ``closeEvent`` shuts its worker down."""
        self.text_translation = TextTranslationWorkspace(self)
        return self.text_translation.build_page()

    # Notices.

    def post_notice(self, notice: Notice) -> bool:
        """Post ``notice``; one of an older session generation than the current is dropped."""
        current = self.session_owner.generation if notice.generation is not None else None
        return self.notices.post(notice, current)

    def conversation_notice(self) -> Notice | None:
        """The Conversation workspace's top notice (scripts and tests)."""
        return self.notices.top(WorkspaceId.CONVERSATION)

    def resolve_notices(self, keys) -> None:
        for key in keys:
            self.notices.resolve(key)

    def _notice_changed(self, change: str, notice: Notice) -> None:
        if change == "posted":
            severity = notice.severity.name.lower()
            self.diagnostics.record("notice", f"{severity} {notice.key}: {notice.title}")
        else:
            self.diagnostics.record("notice", f"resolved {notice.key}")
        if self.current_workspace() is WorkspaceId.SETTINGS:
            self.settings.diagnostics_view.refresh()

    # Shared by the workspaces.

    def session_locked(self) -> bool:
        conversation = self.conversation
        running = conversation.starting or conversation.capture.running
        return running or self.call_bridge.active() or self.meeting.active()

    def prepare_in_background(self, session: SessionPair, ready: Signal) -> None:
        self.start_generation += 1
        generation = self.start_generation

        def prepare() -> None:
            try:
                self.pipeline.prepare(session)
            except Exception as exc:  # noqa: BLE001 - background boundary reports model failures.
                ready.emit(generation, False, str(exc))
            else:
                ready.emit(generation, True, "")

        threading.Thread(target=prepare, name="model-warmup", daemon=True).start()

    def describe_missing(self, availability: ModeAvailability) -> str:
        items = ", ".join(describe(item, self.pipeline.registry) for item in availability.missing)
        return strings.MODE_UNAVAILABLE.format(items=items)

    def show_unavailable(self, missing, mode: WorkspaceId = WorkspaceId.CONVERSATION) -> None:
        """A blocking notice naming every missing item; **Retry** runs ``mode``'s Start gate."""
        title = self.describe_missing(ModeAvailability(False, tuple(missing)))
        retry = self.start_listening if mode is WorkspaceId.CONVERSATION else self.start_call_bridge
        self.post_notice(catalog.mode_unavailable(mode, title, self.notice_source(mode), retry))

    def show_busy(self, mode: WorkspaceId, active: WorkspaceId) -> None:
        """A refused start of ``mode`` while ``active`` holds the session: an info notice."""
        self.post_notice(catalog.session_busy(mode, active))

    def notice_source(self, mode: WorkspaceId) -> str:
        """The ``source`` of a mode's notices: "<Mode> · <languages>"."""
        if mode is WorkspaceId.CONVERSATION:
            return self.conversation.notices.where()
        if mode is WorkspaceId.CALL_BRIDGE:
            return catalog.source(mode, self.call_bridge.lanes_name())
        return catalog.source(mode)
