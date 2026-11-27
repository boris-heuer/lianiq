"""Voice switches, the spoken plan and the Start check of Conversation (CAP-0167 WI-03).

``ConversationWorkspace`` base. The plan is the set of output languages whose voice is ready
and whose switch is on (``voice_status`` / ``spoken_plan``, contract.md §4). Every refresh
shows the rows in Conversation and Settings, writes ``languages.output`` from the plan
(``VoicePreferences.sync_output``) and composes the Start check: CAP-0169 row 5 (or 3) plus
the voice of each planned language and the playback device; with every output language on
it is row 6 (or 4). The plan is bound to the session at Start. A missing voice is shown in
its row, never as a notice (contract.md §8).

WI-04: the playback state of ``SpokenOutput`` mutes the capture on the speaking thread and
reaches the UI thread through ``UiBridge.playback_state``: the state line reads
``VOICE_MIC_PAUSED``, the level bar is 0, and **Replay** / **Stop playback** of both rows get
their enabled states (contract.md §7).

WI-05: **Voice options…** opens ``VoiceOptionsDialog`` with the controls of the language's
voice (read without loading a model, AC-26). While Call Bridge or Meeting holds the session,
**Voice options…** of its languages is locked with ``VOICE_LOCKED_SESSION`` in both places
(AC-18); a running Conversation locks only the switches, the dialog stays usable (AC-16).
"""

from __future__ import annotations

from PySide6.QtCore import Slot

from lianiq.conversation.spoken_output import (
    PlaybackState,
    VoiceState,
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
from lianiq.tts.voice_controls import VoiceControls
from lianiq.ui import strings
from lianiq.ui.shell.session_owner import SessionState
from lianiq.ui.shell.workspaces import WorkspaceId, label
from lianiq.ui.voice_options_dialog import VoiceOptionsDialog

# The modes whose running session keeps the voice options bound at its Start (C §7).
OPTIONS_LOCKING_MODES = {WorkspaceId.CALL_BRIDGE: "call_bridge", WorkspaceId.MEETING: "meeting"}


class ConversationVoice:
    """``ConversationWorkspace`` base: per-language voice output of the selected session."""

    voice_plan: frozenset[LanguageId] | None = None  # ``None`` until the first refresh
    voice_lock: str | None = None  # the switch lock of a running session
    voice_statuses_shown: tuple[VoiceStatus, ...] = ()
    playback_state = PlaybackState.IDLE  # the last state shown on the UI thread
    voice_paused = False  # this page is paused by a playback (speaking thread)
    voice_controls_shown: dict[LanguageId, VoiceControls] = {}  # noqa: RUF012 - replaced
    voice_options_lock: tuple[frozenset[LanguageId], str | None] = (frozenset(), None)
    voice_dialog: VoiceOptionsDialog | None = None

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
        self.voice_controls_shown = self.ready_controls(statuses)
        self.voice_rows.set_rows(statuses, self.voice_preferences, self.voice_controls_shown)
        return plan

    def ready_controls(self, statuses) -> dict[LanguageId, VoiceControls]:
        """The controls of each ready voice; reading them never loads a model (AC-26)."""
        found = {
            status.language: self.pipeline.voice_controls(status.language)
            for status in statuses
            if status.state is VoiceState.READY
        }
        return {language: controls for language, controls in found.items() if controls}

    def planned_session(self, pair: LanguagePair, plan: frozenset[LanguageId]) -> SessionPair:
        """The session of the current controls whose output follows ``plan``."""
        return spoken_session(self.text_session(pair), plan)

    @Slot(str, bool)
    def _voice_switched(self, language: str, on: bool) -> None:
        """A switch in Conversation or Settings: the saved choice; bound at the next Start."""
        if self.host.session_locked():  # the switches are locked: show the bound state
            self.voice_rows.set_rows(
                self.voice_statuses_shown, self.voice_preferences, self.voice_controls_shown
            )
            self.voice_rows_changed.emit()
            return
        self.voice_preferences.set_enabled(LanguageId(language), on)
        self.refresh_availability()

    # Voice options (WI-05) ----------------------------------------------------------------

    @Slot(str)
    def open_voice_options(self, language: str) -> None:
        """**Voice options…** of ``language`` in Conversation or Settings (window-modal)."""
        language_id = LanguageId(language)
        controls = self.voice_controls_shown.get(language_id)
        if controls is None:
            return
        load = None
        if controls.speakers is None:  # a sherpa-onnx voice: its speakers need the model

            def load() -> VoiceControls:
                return self.pipeline.voice_synthesizer().load_controls(language_id)

        def save() -> None:
            if self.host.persist_settings:
                self.config.save()

        dialog = VoiceOptionsDialog(
            language_id,
            controls,
            self.voice_preferences,
            self.pipeline.registry,
            load,
            self.host,
            save,
        )
        dialog.changed.connect(lambda _language: self._voice_options_changed())
        self.voice_dialog = dialog
        dialog.open()

    def _voice_options_changed(self) -> None:
        """A chosen speaker shows in the state text; the plan and switches are unchanged."""
        self.voice_statuses_shown = self.voice_statuses()
        self.voice_rows.set_rows(
            self.voice_statuses_shown, self.voice_preferences, self.voice_controls_shown
        )
        self.voice_rows_changed.emit()

    def _voice_session_changed(self, state: SessionState, active: WorkspaceId | None) -> None:
        """Call Bridge or Meeting running: **Voice options…** of its languages is locked."""
        name = OPTIONS_LOCKING_MODES.get(active) if active is not None else None
        if state is SessionState.IDLE or name is None:
            self.voice_options_lock = (frozenset(), None)
        else:
            try:
                languages = frozenset(getattr(self.host, name).session().pair.members)
            except Exception:  # noqa: BLE001 - an invalid setting: lock every row
                languages = frozenset(self.voice_rows.languages())
            reason = strings.VOICE_LOCKED_SESSION.format(mode=label(active))
            self.voice_options_lock = (languages, reason)
        self.voice_rows.set_options_locked(*self.voice_options_lock)
        self.voice_rows_changed.emit()

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

    # Playback state (WI-04) ---------------------------------------------------------------

    def on_playback_state(self, state: PlaybackState) -> None:
        """``SpokenOutput.on_state`` on the speaking thread: mute now, show it on the UI thread.

        A per-turn replay pauses this page only while its session runs or when it was started
        here (paired-transcript §3.3); a replay of the Listen page leaves it as it is.
        """
        paused = state is not PlaybackState.IDLE
        if paused and not self.voice_paused:
            replay = self.pipeline.spoken.active_replay
            here = self.starting or self.capture.running or self.replayer.owns(replay)
            if replay is not None and not here:
                return
        elif not paused and not self.voice_paused:
            return  # the pause of another page ended
        self.voice_paused = paused
        self.capture.set_muted(paused)
        self.host.bridge.playback_state.emit(state.value)

    @Slot(str)
    def _show_playback_state(self, value: str) -> None:
        self.playback_state = PlaybackState(value)
        if self.playback_state is PlaybackState.IDLE:
            self.state_label.setText(self.activity_text())
        else:
            self.level_bar.setValue(0)
            self.state_label.setText(strings.VOICE_MIC_PAUSED)
        self.refresh_playback()

    def can_replay(self) -> bool:
        """A running session has a spoken translation it still speaks (AC-12)."""
        spoken = self.pipeline.spoken
        last = None if spoken is None else spoken.last_spoken
        capture = getattr(self, "capture", None)  # built after the controls
        running = capture is not None and capture.running
        return running and last is not None and last.target_language in spoken.plan

    def refresh_playback(self) -> None:
        """**Replay** and **Stop playback** in Conversation, then the Settings mirror."""
        self.voice_rows.set_playback(self.playback_state, self.can_replay())
        self.voice_rows_changed.emit()
