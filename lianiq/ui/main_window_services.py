"""Session, notice and warm-up services ``MainWindow`` shares (CAP-0168 file-size split)."""

from __future__ import annotations

import threading

from PySide6.QtCore import Signal

from lianiq.languages.modes import SessionPair
from lianiq.languages.requirements import ModeAvailability, describe
from lianiq.ui import notice_catalog as catalog
from lianiq.ui import strings
from lianiq.ui.notices import Notice
from lianiq.ui.shell.session_owner import SessionState
from lianiq.ui.shell.workspaces import WorkspaceId


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
        return conversation.starting or conversation.capture.running or self.call_bridge.active()

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
