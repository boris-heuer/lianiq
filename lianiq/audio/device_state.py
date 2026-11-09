"""The refresh strategy of the Conversation device lists (CAP-0168 contract §4).

Qt-free. PortAudio fixes its device list when it initialises, while the native identities
are read live from Windows. A full refresh (PortAudio re-initialisation, then a new
inventory) therefore runs only while no stream is open. While a stream is open, only the
native identities are compared (the 2 s monitor and a guarded **Refresh**): a change is
reported, the lists are marked "refresh after Stop" and ``after_stop`` runs the full refresh.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace

from lianiq.audio.device_inventory import ConversationInventory
from lianiq.audio.device_selection import InventoryChange, diff_inventory, diff_native

NATIVE_PREFIX = "windows-mmdevice:"
MONITOR_INTERVAL_MS = 2_000


class DeviceState:
    def __init__(
        self,
        read: Callable[[], ConversationInventory],
        reinitialize: Callable[[], None],
        read_native: Callable[[], Mapping[str, str]],
    ) -> None:
        self._read = read
        self._reinitialize = reinitialize
        self._read_native = read_native
        self.inventory = ConversationInventory()
        self.loaded = False
        self.refresh_pending = False
        self.full_refreshes = 0
        # Native ID -> name of the last observation; ``None`` when Windows cannot be read.
        self.known_native: dict[str, str] | None = None

    def load(self) -> None:
        """The first read at start-up: PortAudio is freshly initialised, no re-init."""
        self.inventory = self._read()
        self.known_native = self._native()
        self.loaded = True
        self.refresh_pending = False

    def refresh(self, streams_open: bool) -> InventoryChange:
        """**Refresh**: full while no stream is open, otherwise the identity check only."""
        if streams_open:
            change = self.check_identities()
            self.refresh_pending = True
            return change
        before = self.inventory
        if self.loaded:
            self._reinitialize()  # spec §9 T5; never while a stream is open
        self.full_refreshes += 1
        self.load()
        change = diff_inventory(before.endpoints, self.inventory.endpoints)
        return replace(
            change, default_changed=dict(before.defaults) != dict(self.inventory.defaults)
        )

    def check_identities(self) -> InventoryChange:
        """Compare the live native identities with the last observation (no PortAudio)."""
        current = self._native()
        if current is None or self.known_native is None:
            return InventoryChange()
        change = diff_native(self.inventory.endpoints, self.known_native, current)
        self.known_native = current
        if not change.is_empty():
            self.refresh_pending = True
        return change

    def after_stop(self) -> InventoryChange | None:
        """The last stream closed: run the pending full refresh, if any."""
        return self.refresh(False) if self.refresh_pending else None

    def present(self, endpoint_id: str) -> bool:
        """Whether a native identity is still active; other identities cannot be checked."""
        if self.known_native is None or not endpoint_id.startswith(NATIVE_PREFIX):
            return True
        return endpoint_id in self.known_native

    def _native(self) -> dict[str, str] | None:
        try:
            return dict(self._read_native())
        except (OSError, RuntimeError):
            return None
