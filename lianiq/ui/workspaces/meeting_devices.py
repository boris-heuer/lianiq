"""The Meeting device panel: endpoints by identity, partner suggestion, readiness (CAP-0177).

``MeetingWorkspace`` base (file-size split). The combos list the Conversation inventory of
Settings › Audio devices (``DeviceSetup.state``), never another list. *Table microphone*,
*Table speaker* and the output for local-language speech are explicit only (contract.md §1):
their first item chooses nothing. *Your microphone* follows the Windows default
(``Follow Windows default (now: <name>)``) or names an explicit endpoint (CAP-0168
``DevicePolicy``). A saved endpoint that is missing stays selected as "Saved device —
unavailable"; no other device is ever chosen instead. Choosing a table endpoint suggests the
other-flow endpoint of the same device (``suggest_table_partner``) for a partner that is not
assigned (or no longer present); the PO can override it.

Choices are written to ``config.meeting`` at once and saved with the settings
(``config/settings.local.json``); display names are never stored.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox

from lianiq.audio.device_selection import (
    FOLLOW_DEFAULT,
    DeviceChoice,
    DevicePolicy,
    UnusableEndpoint,
    describe,
    display_labels,
    resolve_choice,
    unusable_reason,
)
from lianiq.call_bridge.contracts import AudioEndpointRef, EndpointFlow
from lianiq.languages.requirements import DeviceReadiness
from lianiq.meeting.contracts import (
    EndpointConflict,
    MeetingEndpoints,
    MeetingRole,
    suggest_table_partner,
)
from lianiq.ui import strings

MISSING = "\x00missing"  # combo data of the "Saved device — unavailable" item
FLOWS = {
    MeetingRole.TABLE_CAPTURE: EndpointFlow.CAPTURE,
    MeetingRole.TABLE_RENDER: EndpointFlow.RENDER,
    MeetingRole.USER_CAPTURE: EndpointFlow.CAPTURE,
    MeetingRole.LOCAL_RENDER: EndpointFlow.RENDER,
}
# ``config.meeting`` key of each role's endpoint ID (contract.md §8).
SETTING = {
    MeetingRole.TABLE_CAPTURE: "table_capture_endpoint_id",
    MeetingRole.TABLE_RENDER: "table_render_endpoint_id",
    MeetingRole.USER_CAPTURE: "user_input_endpoint_id",
    MeetingRole.LOCAL_RENDER: "local_output_endpoint_id",
}
# The roles requirement row 8 needs (every role but the optional local-speech output).
CAPTURE_OR_TABLE = frozenset(MeetingRole) - {MeetingRole.LOCAL_RENDER}
PARTNERS = {
    MeetingRole.TABLE_CAPTURE: MeetingRole.TABLE_RENDER,
    MeetingRole.TABLE_RENDER: MeetingRole.TABLE_CAPTURE,
}
# Each ``EndpointConflict``: the role it removes from the ready roles (contract.md §6) and
# the table role it collides with.
CONFLICT_ROLES = {
    EndpointConflict.USER_IS_TABLE: (MeetingRole.USER_CAPTURE, MeetingRole.TABLE_CAPTURE),
    EndpointConflict.LOCAL_IS_TABLE: (MeetingRole.LOCAL_RENDER, MeetingRole.TABLE_RENDER),
}


class MeetingDevices:
    """``MeetingWorkspace`` base: the four endpoint combos and what they resolve to."""

    def inventory(self):
        return self.host.device_setup.state.inventory

    def user_choice(self) -> DeviceChoice:
        meeting = self.config.meeting
        if meeting.user_input_policy == DevicePolicy.EXPLICIT.value:
            return DeviceChoice(DevicePolicy.EXPLICIT, meeting.user_input_endpoint_id)
        return FOLLOW_DEFAULT

    def endpoint(self, role: MeetingRole) -> AudioEndpointRef | None:
        """The usable endpoint ``role`` resolves to now, or ``None`` (never a substitute)."""
        inventory, flow = self.inventory(), FLOWS[role]
        if role is MeetingRole.USER_CAPTURE:
            choice = self.user_choice()
            return resolve_choice(
                choice, inventory.endpoints, flow, inventory.default(flow)
            ).endpoint
        wanted = getattr(self.config.meeting, SETTING[role])
        return next(
            (
                e
                for e in inventory.endpoints
                if e.endpoint_id == wanted
                and e.flow is flow
                and not isinstance(e, UnusableEndpoint)
            ),
            None,
        )

    def conflicts(self) -> tuple[EndpointConflict, ...]:
        """The conflicts of the resolved endpoints, by endpoint ID (contract.md §1)."""
        return tuple(
            conflict
            for conflict, (role, table) in CONFLICT_ROLES.items()
            if (mine := self.endpoint(role)) is not None
            and (theirs := self.endpoint(table)) is not None
            and mine.endpoint_id == theirs.endpoint_id
        )

    def device_readiness(self) -> DeviceReadiness:
        """Assigned, non-conflicting roles for requirement row 8 and the speech switch."""
        ready = {role.value for role in MeetingRole if self.endpoint(role) is not None}
        for conflict in self.conflicts():
            ready.discard(CONFLICT_ROLES[conflict][0].value)
        return DeviceReadiness(meeting_endpoints=frozenset(ready))

    def meeting_endpoints(self) -> MeetingEndpoints:
        """The resolved endpoints for the controller; raises if a row 8 role is missing."""
        found = {role: self.endpoint(role) for role in MeetingRole}
        unassigned = [r.value for r in MeetingRole if found[r] is None and r in CAPTURE_OR_TABLE]
        if unassigned:  # Start is gated on row 8, so only a device change can get here
            raise RuntimeError(f"Meeting endpoints not resolved: {', '.join(unassigned)}")
        return MeetingEndpoints(
            found[MeetingRole.TABLE_CAPTURE],
            found[MeetingRole.TABLE_RENDER],
            found[MeetingRole.USER_CAPTURE],
            found[MeetingRole.LOCAL_RENDER],
            self.config.meeting.local_output_is_headset,
        )

    # Combos -------------------------------------------------------------------------------

    def load_endpoints(self) -> None:
        """Fill the combos from the current inventory, keeping every saved choice."""
        inventory = self.inventory()
        labels = display_labels(inventory.endpoints)
        for role, combo in self.combos.items():
            flow = FLOWS[role]
            combo.blockSignals(True)
            combo.clear()
            if role is MeetingRole.USER_CAPTURE:
                default = inventory.default(flow)
                follow = resolve_choice(FOLLOW_DEFAULT, inventory.endpoints, flow, default)
                combo.addItem(follow.label, None)
            else:
                combo.addItem(strings.DEVICE_CHOOSE, None)
            for endpoint in inventory.endpoints:
                if endpoint.flow is not flow:
                    continue
                text = labels[endpoint.endpoint_id]
                unusable = isinstance(endpoint, UnusableEndpoint)
                if unusable:
                    text = strings.DEVICE_UNUSABLE.format(name=text, reason=unusable_reason(flow))
                combo.addItem(text, endpoint.endpoint_id)
                index = combo.count() - 1
                combo.setItemData(index, describe(endpoint), Qt.ItemDataRole.ToolTipRole)
                combo.model().item(index).setEnabled(not unusable)
            combo.setCurrentIndex(self._saved_index(role, combo))
            target = self.endpoint(role)
            combo.setAccessibleDescription(
                combo.currentText() if target is None else describe(target)
            )
            combo.setToolTip(combo.accessibleDescription())
            combo.blockSignals(False)
        self.refresh()

    def _saved_index(self, role: MeetingRole, combo: QComboBox) -> int:
        if (
            role is MeetingRole.USER_CAPTURE
            and self.user_choice().policy is DevicePolicy.FOLLOW_DEFAULT
        ):
            return 0
        wanted = getattr(self.config.meeting, SETTING[role])
        if wanted is None:
            return 0
        index = combo.findData(wanted)
        if index < 0:  # the saved device stays selected, shown as unavailable
            combo.addItem(strings.DEVICE_UNAVAILABLE.format(name=strings.DEVICE_SAVED), MISSING)
            index = combo.count() - 1
            combo.model().item(index).setEnabled(False)
        return index

    def choose(self, role: MeetingRole, endpoint_id: str | None) -> None:
        """Store the choice of ``role`` (``None``: none, or follow the default)."""
        meeting = self.config.meeting
        setattr(meeting, SETTING[role], endpoint_id)
        if role is MeetingRole.USER_CAPTURE:
            policy = DevicePolicy.FOLLOW_DEFAULT if endpoint_id is None else DevicePolicy.EXPLICIT
            meeting.user_input_policy = policy.value

    def _combo_activated(self, role: MeetingRole) -> None:
        data = self.combos[role].currentData()
        if data == MISSING:
            return
        self.choose(role, data)
        partner = PARTNERS.get(role)
        chosen = self.endpoint(role)
        # The suggestion fills an unassigned partner only; a choice of the PO is kept.
        if partner is not None and chosen is not None and self.endpoint(partner) is None:
            usable = [e for e in self.inventory().endpoints if not isinstance(e, UnusableEndpoint)]
            suggestion = suggest_table_partner(chosen, usable)
            if suggestion is not None:
                self.choose(partner, suggestion.endpoint_id)
        self.load_endpoints()
