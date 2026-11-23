"""Voice switches, the spoken plan and the Start check of Conversation (CAP-0167 WI-03).

``ConversationWorkspace`` base. The plan is the set of output languages whose voice is ready
and whose switch is on (``voice_status`` / ``spoken_plan``, contract.md §4). Every refresh
shows the rows in Conversation and Settings, writes ``languages.output`` from the plan
(``VoicePreferences.sync_output``) and composes the Start check: CAP-0169 row 5 (or 3) plus
the voice of each planned language and the playback device; with every output language on
it is row 6 (or 4). The plan is bound to the session at Start. A missing voice is shown in
its row, never as a notice (contract.md §8).
"""

from __future__ import annotations

from PySide6.QtCore import Slot

from lianiq.conversation.spoken_output import (
    VoiceStatus,
    output_languages,
    spoken_plan,
    spoken_session,
    start_check,
    voice_status,
)
from lianiq.languages.modes import OutputKind, SessionPair
from lianiq.languages.registry import LanguageId, LanguagePair
from lianiq.languages.requirements import ModeAvailability
from lianiq.ui.shell.workspaces import WorkspaceId


class ConversationVoice:
    """``ConversationWorkspace`` base: per-language voice output of the selected session."""

    voice_plan: frozenset[LanguageId] | None = None  # ``None`` until the first refresh
    voice_lock: str | None = None  # the switch lock of a running session
    voice_statuses_shown: tuple[VoiceStatus, ...] = ()

    def _packs(self):
        workspace = getattr(self.host, "language_packs", None)
        return getattr(workspace, "packs", None)

    def text_session(self, pair: LanguagePair) -> SessionPair:
        return self.conversation_session(pair, self.current_fixed_source(), OutputKind.TEXT)

    def voice_statuses(self) -> tuple[VoiceStatus, ...]:
        """One status per pair language, in pair order; empty without a ready pair."""
        pair = self.current_pair()
        if pair is None:
            return ()
        outputs = output_languages(self.text_session(pair))
        return tuple(
            voice_status(
                language,
                catalog=self.session_controller.catalog,
                config=self.config,
                registry=self.pipeline.registry,
                outputs=outputs,
                packs=self._packs(),
            )
            for language in pair.members
        )

    def current_plan(self) -> frozenset[LanguageId]:
        """The languages a Start now would speak."""
        return spoken_plan(self.voice_statuses(), self.config)

    def start_availability(
        self, session: SessionPair, plan: frozenset[LanguageId]
    ) -> ModeAvailability:
        """The composed Start check of ``session`` speaking ``plan`` (contract.md §4)."""
        return start_check(session, plan, self.session_controller.catalog, self.device_readiness())

    def refresh_voice_rows(self) -> frozenset[LanguageId]:
        """Show the rows, keep ``languages.output`` in step with the plan; returns the plan."""
        statuses = self.voice_statuses()
        plan = spoken_plan(statuses, self.config)
        self.voice_statuses_shown = statuses
        self.voice_plan = plan
        if statuses:
            self.voice_preferences.sync_output(plan)
        self.voice_rows.set_rows(statuses, self.voice_preferences, {})
        return plan

    def planned_session(self, pair: LanguagePair, plan: frozenset[LanguageId]) -> SessionPair:
        """The session of the current controls whose output follows ``plan``."""
        return spoken_session(self.text_session(pair), plan)

    @Slot(str, bool)
    def _voice_switched(self, language: str, on: bool) -> None:
        """A switch in Conversation or Settings: the saved choice; bound at the next Start."""
        if self.host.session_locked():  # the switches are locked: show the bound state
            self.voice_rows.set_rows(self.voice_statuses_shown, self.voice_preferences, {})
            self.voice_rows_changed.emit()
            return
        self.voice_preferences.set_enabled(LanguageId(language), on)
        self.refresh_availability()

    @Slot()
    def open_language_packs(self) -> None:
        self.host.show_workspace(WorkspaceId.LANGUAGE_PACKS)

    @Slot()
    def replay_spoken(self) -> None:
        spoken = self.pipeline.spoken
        if spoken is not None:
            spoken.replay()

    @Slot()
    def stop_spoken(self) -> None:
        spoken = self.pipeline.spoken
        if spoken is not None:
            spoken.stop_playback()
