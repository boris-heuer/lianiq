"""Unavailable devices and **Refresh** of ``DeviceSetup`` (CAP-0168 WI-04 file-size split).

- A saved explicit device that is missing or unusable gets one blocking notice per flow with
  **Choose device**; Start is refused while it is selected (spec §2.2.4, AC-14, AC-17).
- **Refresh** is full only while no stream is open (contract §4 "Refresh strategy"); during
  a session or a device test it reports the identity change (``DEVICE_CHANGED``) and the
  full refresh runs after Stop. A new Windows default of a flow that follows it is named in
  an info notice (AC-16). After a full refresh the Call Bridge lists are re-read, because
  PortAudio indices may have moved; its selections are kept by identity.
"""

from __future__ import annotations

from PySide6.QtCore import Slot

from lianiq.audio.device_selection import DevicePolicy, display_labels
from lianiq.ui import notice_catalog as catalog
from lianiq.ui import strings
from lianiq.ui.device_watch import CAPTURE, FLOW_NAMES, RENDER


class DeviceRefresh:
    # Unavailable or unusable saved devices (spec §2.2.4, AC-14, AC-17) ------------------

    def post_unavailable(self, refused: bool = False, spoken: bool | None = None) -> bool:
        """Post or resolve the per-flow notice; ``True`` if a relevant choice is not ready."""
        spoken = self.config.voice_output if spoken is None else spoken
        blocked = False
        for flow in (CAPTURE, RENDER):
            resolved, key = self.resolved(flow), catalog.device_unavailable_key(FLOW_NAMES[flow])
            relevant = flow is CAPTURE or spoken
            if resolved.choice.policy is DevicePolicy.FOLLOW_DEFAULT or resolved.ready:
                self.host.notices.resolve(key)
                continue
            if not relevant:
                continue
            blocked = True
            name = resolved.choice.display_name or strings.DEVICE_SAVED
            if resolved.available:  # present but unusable
                name = display_labels(self.state.inventory.endpoints)[resolved.choice.endpoint_id]
            notice = catalog.device_unavailable(
                FLOW_NAMES[flow], name, self.where(), self.choose(flow), resolved.reason
            )
            live = self.host.notices.get(key)
            if refused or live is None or live.title != notice.title:
                self.host.post_notice(notice)
        return blocked

    def refuse_start(self, spoken: bool) -> bool:
        """Start is refused while a saved explicit device is missing or unusable."""
        return self.post_unavailable(refused=True, spoken=spoken)

    # Refresh ----------------------------------------------------------------------------

    def streams_open(self) -> bool:
        return self.testing or self.host.session_locked()

    @Slot()
    def refresh(self) -> bool:
        """**Refresh**; ``True`` when the full refresh ran (no stream open)."""
        before = dict(self.state.inventory.defaults)
        streams_open = self.streams_open()
        try:
            change = self.state.refresh(streams_open)
        except (OSError, RuntimeError, ValueError) as exc:
            self.host.show_error(str(exc))
            return False
        if streams_open:
            if not change.is_empty():
                self.host.post_notice(catalog.devices_changed(change.summary(), self.where()))
            return False
        self.after_full_refresh()
        labels = display_labels(self.state.inventory.endpoints)
        for flow in (CAPTURE, RENDER):
            default = self.state.inventory.default(flow)
            following = self.choices[flow].policy is DevicePolicy.FOLLOW_DEFAULT
            if following and default is not None and before.get(flow) != default.endpoint_id:
                name = labels[default.endpoint_id]
                self.host.post_notice(catalog.default_changed(FLOW_NAMES[flow], name, self.where()))
        return True

    def after_full_refresh(self) -> None:
        self.fill()
        self.host.conversation.refresh_availability()
        panel = self.host.call_bridge_panel
        selected = {role: combo.currentData() for role, combo in panel.endpoint_combos.items()}
        self.host.call_bridge.load_endpoints()
        for role, combo in panel.endpoint_combos.items():
            index = combo.findData(selected[role]) if selected[role] else -1
            if index >= 0:
                combo.setCurrentIndex(index)
