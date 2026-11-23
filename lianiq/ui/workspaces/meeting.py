"""The Meeting workspace: setup, Start availability and the session lifecycle (CAP-0177 WI-04).

Sidebar entry *Meeting*, second (Ctrl+2). The page offers the session pair, the device panel
(``meeting_devices``) and the options. **Start meeting** follows requirement row 8
(``MEETING_MODE``): disabled while a recognition, translation or table-language voice is
missing or a device role is missing or in conflict, each listed under the options
(``ModeAvailability.missing``, the conflict by its text). The local-speech switch follows
``meeting_local_speech_requirements`` and never blocks Start (contract.md §1, §6).

The ``MeetingController`` is built only at Start, after the models are prepared, by the
factory ``lianiq.app`` registers (``MainWindow(meeting_factory=...)``). It sees the
``ActiveSessionOwner`` through ``_ControllerOwner``: the page reserves the session before
the models load, so the controller's own ``request_start`` takes that reservation, and its
``register`` cannot replace the page's stopper. A start while Conversation or Call Bridge
holds the session is refused with the busy notice and opens nothing; theirs are refused
while the meeting holds it (AC-19).

``stop()`` of the controller drains for up to 120 s, so it never runs on the GUI thread: the
page's asynchronous stopper (F9, **End meeting**, closing) runs it on a worker thread, and
the session stays *stopping* until ``STOPPED`` (or a failed drain) reaches the GUI thread,
which then marks it idle; until then every other start is refused (AC-19). The
controller's ``mark_idle``, its events and the input levels reach the GUI thread through
queued signals (the ``UiBridge`` hand-off pattern). The running view and the status strip
are ``meeting_running`` (WI-05), device loss and the end-of-meeting dialog
``meeting_notices``. **Speak {language} for me** can change while the meeting runs (AC-05).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Signal

from lianiq.languages.errors import LanguageContractError
from lianiq.languages.modes import MEETING_MODE, SessionPair
from lianiq.languages.requirements import (
    ModeAvailability,
    check,
    describe,
    is_met,
    meeting_local_speech_requirements,
)
from lianiq.meeting.contracts import EndpointConflict, TableInputDuringOutput
from lianiq.ui import strings
from lianiq.ui.shell.session_owner import SessionState
from lianiq.ui.shell.workspaces import session_busy_message
from lianiq.ui.workspaces.meeting_devices import CONFLICT_ROLES, MeetingDevices
from lianiq.ui.workspaces.meeting_layout import MeetingLayout
from lianiq.ui.workspaces.meeting_lifecycle import MEETING, MeetingLifecycle
from lianiq.ui.workspaces.meeting_notices import MeetingEnd
from lianiq.ui.workspaces.meeting_running import MeetingRunning

if TYPE_CHECKING:
    from lianiq.ui.main_window import MainWindow


class MeetingWorkspace(
    MeetingLayout, MeetingDevices, MeetingLifecycle, MeetingRunning, MeetingEnd, QObject
):
    models_ready = Signal(int, bool, str)  # start generation, ready, error message
    meeting_event = Signal(object)  # MeetingEvent, from the capture and worker threads
    meeting_level = Signal(object, float)  # input role, level, from the capture threads
    owner_idle = Signal(int)  # the controller's mark_idle, from the stopping thread

    def __init__(self, host: MainWindow) -> None:
        super().__init__(host)
        self.host, self.config, self.pipeline = host, host.config, host.pipeline
        self.owner = host.session_owner
        self.controller = None
        self.starting = False
        self.stopping = False
        self._generation = 0  # the owner generation of this workspace's latest start
        self._pending: SessionPair | None = None
        self.models_ready.connect(self._models_ready)
        self.meeting_event.connect(self._event)
        self.meeting_level.connect(self.show_level)
        self.owner_idle.connect(self.owner.mark_idle)
        self.owner.register(MEETING, self.stop_meeting, asynchronous=True)
        self.owner.subscribe(self._session_changed)

    def connect_selection(self) -> None:
        """After the Conversation pair control is filled: follow it and list the devices."""
        pair_combo = self.host.conversation.pair_combo
        pair_combo.currentIndexChanged.connect(lambda _index: self.refresh())
        self.load_endpoints()

    def active(self) -> bool:
        """A meeting loads its models, runs or still drains its contributions."""
        return self.controller is not None or self.starting

    # The session and what it needs ---------------------------------------------------------

    def session(self) -> SessionPair:
        registry = self.pipeline.registry
        return SessionPair(
            registry.pair(*self.config.languages.pair),
            MEETING_MODE,
            local_language=registry.get(self.config.meeting.local_language).id,
        )

    def language_names(self) -> tuple[str, str]:
        """Registry names of the local and the table language."""
        registry = self.pipeline.registry
        try:
            local = registry.get(self.config.meeting.local_language).id
            pair = registry.pair(*self.config.languages.pair)
        except LanguageContractError:  # an invalid setting is named by the availability
            return self.config.meeting.local_language, ""
        table = pair.other(local) if local in pair else pair.second
        return registry.display_name(local), registry.display_name(table)

    def availability(self) -> ModeAvailability:
        return check(self.session(), self.pipeline.catalog, self.device_readiness())

    def missing_text(self, missing) -> str:
        """Each missing item, in order; a role removed by a conflict is named by its conflict.

        "Not available: missing <items>", then one line per conflict (contract.md §6, §7).
        """
        if not missing:
            return ""
        local_name, _table = self.language_names()
        local = self.session().local_language
        conflicts = {
            CONFLICT_ROLES[c][0].value: _conflict_text(c, local_name) for c in self.conflicts()
        }
        registry = self.pipeline.registry
        items = [
            describe(item, registry, local_language=local)
            for item in missing
            if str(item.subject) not in conflicts
        ]
        lines = [strings.MODE_UNAVAILABLE.format(items=", ".join(items))] if items else []
        lines += [
            conflicts[str(item.subject)] for item in missing if str(item.subject) in conflicts
        ]
        return "\n".join(lines)

    def refresh(self) -> None:
        """Pair, labels, the speech switch and **Start meeting** from the current state."""
        self._show_pairs()
        self.name_languages()
        busy = self.active()
        try:
            availability = self.availability()
            speech_missing = [
                item
                for item in meeting_local_speech_requirements(self.session())
                if not is_met(item, self.pipeline.catalog, self.device_readiness())
            ]
        except Exception as exc:  # noqa: BLE001 - an invalid pair or local language setting.
            availability, speech_missing, problem = None, [], str(exc)
        else:
            problem = self.missing_text(availability.missing)
        self.start_button.setEnabled(
            not busy and availability is not None and availability.available
        )
        blocked = self.owner.busy_for(MEETING)
        self.start_button.setToolTip(session_busy_message(blocked) if blocked else problem)
        self.availability_label.setText(problem)
        self.availability_label.setAccessibleName(problem or strings.DIAG_READY)
        speech_reason = self.missing_text(speech_missing)
        checkbox = self.speak_local_checkbox
        checkbox.blockSignals(True)
        settling = self.starting or self.stopping  # switchable while running (AC-05)
        checkbox.setEnabled(not settling and availability is not None and not speech_missing)
        checkbox.setChecked(self.config.meeting.speak_local and not speech_missing)
        checkbox.setToolTip(speech_reason)
        checkbox.setAccessibleDescription(speech_reason)
        checkbox.blockSignals(False)
        self.show_running(busy)
        if not busy:
            self.state_label.setText("" if problem else strings.DIAG_READY)

    def _show_pairs(self) -> None:
        """The session pair, as the Conversation pair control lists and selects it."""
        source, combo = self.host.conversation.pair_combo, self.pair_combo
        combo.blockSignals(True)
        combo.clear()
        for index in range(source.count()):
            combo.addItem(source.itemText(index), source.itemData(index))
            combo.model().item(index).setEnabled(source.model().item(index).isEnabled())
        combo.setCurrentIndex(source.currentIndex())
        combo.blockSignals(False)

    def _pair_activated(self, index: int) -> None:
        self.host.conversation.pair_combo.setCurrentIndex(index)  # one session pair
        self.refresh()

    def _headset_toggled(self, on: bool) -> None:
        self.config.meeting.local_output_is_headset = on

    def _speak_local_toggled(self, on: bool) -> None:
        self.config.meeting.speak_local = on
        if self.controller is None or self.stopping:
            return
        try:
            self.controller.set_speak_local(on)
            self.host.usage_tracker.set_local_speech(on)  # its voice is now in use (C §8)
        except ValueError:  # no German output of its own in this meeting: revert, say why
            self.config.meeting.speak_local = False
            checkbox = self.speak_local_checkbox
            checkbox.blockSignals(True)
            checkbox.setChecked(False)
            checkbox.blockSignals(False)
            reason = _conflict_text(EndpointConflict.LOCAL_IS_TABLE, self.language_names()[0])
            checkbox.setToolTip(reason)
            checkbox.setAccessibleDescription(reason)

    def _table_mode_chosen(self, mode: TableInputDuringOutput) -> None:
        self.config.meeting.table_input_during_output = mode.value  # used at the next Start

    def _session_changed(self, _state: SessionState, _active) -> None:
        if hasattr(self, "start_button"):
            self.refresh()


def _conflict_text(conflict: EndpointConflict, local_name: str) -> str:
    if conflict is EndpointConflict.USER_IS_TABLE:
        return strings.MEETING_CONFLICT_USER_IS_TABLE
    return strings.MEETING_CONFLICT_LOCAL_IS_TABLE.format(language=local_name)
