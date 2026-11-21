"""The Language packs workspace (CAP-0171 WI-04; spec §2.2.2, §2.2.3, §2.3).

Rows come from ``language_rows``; the page overlays ``pack_status`` for every catalog pack.
Statuses are computed on a worker thread (they may hash pack files) and, like every job
event of the one ``PackJobRunner``, reach the Qt thread through ``UiBridge.packs_event``.
Nothing connects before **Download**. A failed or cancelled job leaves the row in its
previous state with the reason and **Retry** (AC-09); logs and Diagnostics name only pack
id, version, operation, phase, state and error class (AC-27).
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Slot
from PySide6.QtWidgets import QWidget

from lianiq.languages.capabilities import CapabilityCatalog, ReadinessProbe
from lianiq.packs.catalog import BUILTIN_CATALOG_PATH, PackCatalog, PackDefinition
from lianiq.packs.disk import free_bytes
from lianiq.packs.errors import ConnectionUnavailable, ManifestError, PackError
from lianiq.packs.import_source import ImportSource
from lianiq.packs.installer import PackInstaller
from lianiq.packs.jobs import PackJobRunner
from lianiq.packs.manifest import Manifest
from lianiq.packs.protection import ActiveUsageTracker, in_use_guard
from lianiq.packs.sources import DownloadSource, HttpsTransport
from lianiq.packs.state import PackState, PackStatus, pack_status, readiness_pack_files
from lianiq.ui import strings
from lianiq.ui.workspaces.language_packs_layout import LanguagePacksLayout, Listener, confirm_remove
from lianiq.ui.workspaces.language_packs_rows import (
    broken_usages,
    capability_text,
    error_text,
    format_size,
    needed_by,
    pack_languages,
    profile_sessions,
)
from lianiq.ui.workspaces.pack_details_dialog import PackDetailsDialog

if TYPE_CHECKING:
    from lianiq.ui.main_window import MainWindow

_LOG = logging.getLogger("lianiq.ui.language_packs")
MANIFEST_RELATIVE = "models/model-manifest.json"
READY = (PackState.INSTALLED, PackState.VALIDATED)


class LanguagePacksWorkspace(QObject):
    def __init__(self, host: MainWindow) -> None:
        super().__init__(host)
        self.host = host
        self.registry = host.pipeline.registry
        self.root = host.pipeline.catalog.probe.root
        self.models = self.root / "models"
        self.manifest_path = self.root / MANIFEST_RELATIVE
        self.packs = PackCatalog.load(BUILTIN_CATALOG_PATH, self.registry)
        self.sessions = profile_sessions(self.registry)
        self.tracker = ActiveUsageTracker(host.session_owner)
        self.transport = HttpsTransport()  # used only when **Download** is clicked
        self.installer = PackInstaller(
            self.root,
            self.manifest_path,
            lambda: datetime.now(UTC),
            catalog=self.packs,
            free_space=lambda folder: free_bytes(folder),  # looked up per call
        )
        guard = in_use_guard(host.session_owner, self.tracker, self.packs, self.installed_ids)
        executor = ThreadPoolExecutor(1, thread_name_prefix="pack-job")
        self.runner = PackJobRunner(self.installer, executor, guard=guard)
        self.statuses: dict = {}
        self.installed: dict[str, str] = {}  # pack id → recorded version
        self.messages: dict[str, tuple[str, bool]] = {}  # pack id → (reason, offline)
        self.requests: dict[str, tuple] = {}  # pack id → the last job, for **Retry**
        self.custom: dict[str, str] = {}
        self.free = 0
        self._generation = 0
        self.details: PackDetailsDialog | None = None

    def build_page(self) -> QWidget:
        self.layout = LanguagePacksLayout(self.registry, self.packs, self.sessions)
        self.host.bridge.packs_event.connect(self._event)
        return self.layout.build(self._actions)

    @property
    def rows(self):
        return self.layout.rows

    def _actions(self, pack_id: str):
        return {
            "primary": lambda: self.open_details(pack_id),
            "remove": lambda: self.remove(pack_id),
            "import": lambda: self.open_details(pack_id),
            "retry": lambda: self.retry(pack_id),
            "cancel": self.runner.cancel,
        }

    def installed_ids(self) -> frozenset[str] | None:
        """``None`` (protect every pack) until a status snapshot exists."""
        if not self.statuses:
            return None
        ready = {key for key, status in self.statuses.items() if status.state in READY}
        return frozenset(ready | set(self.installed))

    # Statuses ----------------------------------------------------------------------------

    def refresh(self) -> None:
        """Recompute every pack status off the Qt thread (the page shows or a job ends)."""
        self._generation += 1
        generation, job = self._generation, self.runner.current
        thread = threading.Thread(
            target=self._compute, args=(generation, job), name="pack-status", daemon=True
        )
        thread.start()

    def _compute(self, generation: int, job) -> None:
        try:
            self._snapshot(generation, job)
        except Exception as error:  # noqa: BLE001 - shown on the page, never a default state
            _LOG.warning("pack status failed error=%s", error.__class__.__name__)
            self.host.bridge.packs_event.emit(("unknown", generation))

    def _snapshot(self, generation: int, job) -> None:
        config = self.host.config
        try:
            manifest = Manifest.read(self.manifest_path)
        except ManifestError:
            manifest = Manifest()
        pack_files = readiness_pack_files(self.packs, manifest, config, self.root)
        probe = ReadinessProbe(self.root, self.manifest_path, pack_files=pack_files)
        catalog = CapabilityCatalog.from_config(config, self.registry, probe)
        statuses, custom = {}, {}
        for pack in self.packs.packs():
            status = pack_status(pack, catalog, manifest, config, job, None)
            statuses[pack.id] = status
            if status.custom_path:
                custom[pack.id] = capability_text(catalog, pack)
        installed = {record.id: record.version for record in manifest.packs}
        free = free_bytes(self.models)
        self.host.bridge.packs_event.emit(
            ("statuses", generation, statuses, custom, installed, free)
        )

    def _show_rows(self) -> None:
        job = self.runner.current
        for pack_id, row in self.rows.items():
            status = self.statuses.get(pack_id)
            message, offline = self.messages.get(pack_id, ("", False))
            if status is None:  # no snapshot: only a refusal shows (e.g. the fail-safe)
                row.message_label.setText(message)
                row.message_label.setVisible(bool(message))
                continue
            if job is not None and job.pack_id == pack_id:
                status = PackStatus(PackState.INSTALLING, None, False, status.custom_path)
            row.show_status(
                status,
                job if job is not None and job.pack_id == pack_id else None,
                message=message,
                offline=offline,
                custom=self.custom.get(pack_id, ""),
                installed=self.installed.get(pack_id, ""),
            )
            row.set_busy(job is not None and job.pack_id != pack_id)
        empty = all(s.state is PackState.DOWNLOADABLE for s in self.statuses.values())
        self.layout.empty_hint.setVisible(bool(self.statuses) and empty)
        folder = strings.PACKS_FOLDER.format(path=self.models, free=format_size(self.free))
        self.layout.folder_label.setText(folder)
        self.layout.folder_label.setAccessibleName(folder)

    @Slot(object)
    def _event(self, event: tuple) -> None:
        kind = event[0]
        if kind == "statuses":
            if event[1] != self._generation:
                return
            _, _, self.statuses, self.custom, self.installed, self.free = event
            self.layout.status_message.setVisible(False)
        elif kind == "unknown":
            if event[1] == self._generation:
                self.statuses, self.installed = {}, {}  # the guard protects every pack
                self.layout.status_message.setVisible(True)
                for row in self.rows.values():
                    row.show_unknown(strings.PACK_STATE_UNKNOWN)
        elif kind == "failed":
            _, pack_id, reason, error = event
            offline = isinstance(error, ConnectionUnavailable)
            self.messages[pack_id] = (error_text(error, reason), offline)
            self._record(pack_id, "failed", error)
            self.refresh()
        elif kind == "finished":
            self._record(event[1], "succeeded", None)
            self.refresh()
        self._show_rows()

    def _record(self, pack_id: str, state: str, error) -> None:
        pack = self.packs.get(pack_id)
        operation = self.requests.get(pack_id, ("install",))[0]
        text = f"pack_id={pack.id} version={pack.version} operation={operation} state={state}"
        if error is not None:
            text += f" error={error.__class__.__name__}"
        self.host.diagnostics.record("packs", text)

    # Jobs --------------------------------------------------------------------------------

    def open_details(self, pack_id: str) -> PackDetailsDialog:
        """The details dialog of ``pack_id``; accepting it starts the download or import."""
        pack = self.packs.get(pack_id)
        status = self.statuses.get(pack_id)
        update = status is not None and status.update_available
        operation = "update" if update else "install"
        dialog = PackDetailsDialog(
            self.host,
            pack,
            pack_languages(pack, self.registry),
            needed_by(pack_id, self.packs, self.sessions),
            free_bytes(self.models),
        )
        dialog.accepted.connect(lambda: self._chosen(pack, operation, dialog))
        self.details = dialog
        dialog.open()
        return dialog

    def _chosen(self, pack: PackDefinition, operation: str, dialog: PackDetailsDialog) -> None:
        kind, path = dialog.choice or ("download", None)
        source = DownloadSource(self.transport) if kind == "download" else ImportSource(path)
        self.start(pack.id, operation, source, datetime.now(UTC))

    def remove(self, pack_id: str) -> None:
        pack = self.packs.get(pack_id)
        ready = frozenset(k for k, s in self.statuses.items() if s.state in READY)
        usages = ", ".join(broken_usages(pack_id, self.packs, self.sessions, ready)) or "—"
        text = strings.PACK_REMOVE_CONFIRM.format(pack=pack.model, usages=usages)
        if confirm_remove(self.host, text):
            self.start(pack_id, "remove", None, None)

    def retry(self, pack_id: str) -> None:
        request = self.requests.get(pack_id)
        if request is not None:
            self.start(pack_id, *request)

    def start(self, pack_id: str, operation: str, source, accepted) -> bool:
        """Start a job; a refusal (busy, in use, no space) shows on the row unchanged."""
        pack = self.packs.get(pack_id)
        self.requests[pack_id] = (operation, source, accepted)
        emit = self.host.bridge.packs_event.emit
        try:
            self.runner.start(
                pack, operation, source, accepted, Listener(emit, self.runner, pack_id)
            )
        except PackError as error:
            self.messages[pack_id] = (error_text(error, str(error)), False)
            self._show_rows()
            return False
        self.messages.pop(pack_id, None)
        self._show_rows()
        return True
