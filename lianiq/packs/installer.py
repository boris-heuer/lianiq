"""The staged pack installer (CAP-0171 contract.md §5). Qt-free, standard library only.

``install``: create ``models/.lianiq-staging/<uuid>/``; TRANSFER the listed files into its
``pack/`` folder; CHECK each (size, SHA-256) and write ``lianiq-pack.json``; SWAP: move each
installed listed file and the old pack file to ``models/.lianiq-previous/<pack id>/``, move
each staged file into the root, write the manifest and commit the journal; then delete the
previous copy and staging. Any error or cancel before the commit undoes the journal, so the
manifest and the root are unchanged. Every path written or removed comes from the catalog
entry (pack root plus listed files), never from a pack-file document or an archive member.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal, Protocol

from lianiq.packs import journal as _journal
from lianiq.packs.catalog import PackCatalog, PackDefinition
from lianiq.packs.disk import free_bytes, required_bytes
from lianiq.packs.errors import (
    InstallCancelled,
    InstallFailed,
    InsufficientSpace,
    ManifestError,
    PackError,
)
from lianiq.packs.jobs import CancelToken, JobPhase, ProgressCallback
from lianiq.packs.journal import (
    Journal,
    delete_tree,
    owned_names,
    prune_empty,
    restore_manifest,
    save_manifest,
    undo,
    unfinished_job,
)
from lianiq.packs.manifest import Manifest, PackRecord
from lianiq.packs.pack_file import (
    FILE_ALTERED,
    FILE_MISSING,
    FILE_WRONG_SIZE,
    PACK_FILE_NAME,
    render_pack_file,
)
from lianiq.packs.paths import is_safe_relative
from lianiq.packs.recovery import recover_models
from lianiq.packs.verify import sha256_file

STAGING_DIR = ".lianiq-staging"
PREVIOUS_DIR = ".lianiq-previous"
FILES_IN_USE = "files are in use"
INSTALL_FAILED = "the install failed ({name})"
REMOVE_FAILED = "the removal failed ({name})"
NOT_RECOVERED = "an earlier job of this pack was not recovered; restart Lianiq"
UNDO_FAILED = "the job could not be undone; restart Lianiq to recover"
UNSAFE_PACK_ID = "the pack id is not a safe folder name"


class Source(Protocol):
    record_source: str

    def fetch(
        self, pack: PackDefinition, staging: Path, progress: ProgressCallback, cancel: CancelToken
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class InstallResult:
    pack_id: str
    version: str
    source: Literal["download", "import", "script"]


class _UndoFailed(InstallFailed):
    """The rollback itself failed: staging and its journal stay for ``recover()``."""

    def __init__(self) -> None:
        super().__init__(UNDO_FAILED)


def _failure(error: OSError, template: str) -> InstallFailed:
    if isinstance(error, PermissionError):
        return InstallFailed(FILES_IN_USE)
    return InstallFailed(template.format(name=error.__class__.__name__))


class PackInstaller:
    def __init__(
        self,
        root: Path,
        manifest_path: Path,
        clock: Callable[[], datetime],
        *,
        catalog: PackCatalog | None = None,
        free_space: Callable[[Path], int] = free_bytes,
    ) -> None:
        self.root = Path(root)
        self.models = self.root / "models"
        self.manifest_path = Path(manifest_path)
        self._clock = clock
        self._catalog = catalog
        self._free_space = free_space

    def check_space(self, pack: PackDefinition) -> None:
        """``InsufficientSpace`` when the models drive has less than ``required_bytes``."""
        required, free = required_bytes(pack), self._free_space(self.models)
        if free < required:
            raise InsufficientSpace(required, free)

    def _previous(self, pack: PackDefinition) -> Path:
        """``models/.lianiq-previous/<pack id>``; the id must be one plain path segment."""
        if not is_safe_relative(pack.id) or "/" in pack.id:
            raise InstallFailed(UNSAFE_PACK_ID)
        previous = self.models / PREVIOUS_DIR / pack.id
        if previous.exists() or unfinished_job(self.models / STAGING_DIR, pack.id):
            raise InstallFailed(NOT_RECOVERED)
        return previous

    def _job(self) -> Path:
        job = self.models / STAGING_DIR / uuid.uuid4().hex
        job.mkdir(parents=True)
        return job

    def _manifest(self) -> Manifest:
        try:
            return Manifest.read(self.manifest_path)
        except ManifestError as error:
            raise InstallFailed(error.reason) from None

    def install(
        self,
        pack: PackDefinition,
        source: Source,
        licence_accepted_at: datetime | None,
        progress: ProgressCallback,
        cancel: CancelToken,
    ) -> InstallResult:
        """Install or update ``pack``; on any failure the previous state stays."""
        kind = source.record_source
        if licence_accepted_at is None and kind != "script":
            raise ValueError("An app install needs the licence acceptance time")
        self.check_space(pack)
        previous = self._previous(pack)
        manifest = self._manifest()
        job = self._job()
        staged = job / "pack"
        staged.mkdir()
        try:
            source.fetch(pack, staged, progress, cancel)
            self._check(pack, staged, progress, cancel)
            (staged / PACK_FILE_NAME).write_bytes(render_pack_file(pack))
            record = PackRecord(
                pack.id, pack.version, kind, self._clock(), pack.licence, licence_accepted_at
            )  # type: ignore[arg-type]
            updated = manifest.with_pack(pack, record)
            self._swap(pack, job, staged, previous, updated, progress, cancel)
        except _UndoFailed:
            raise
        except Exception as error:
            delete_tree(job)
            _remove_if_empty(previous.parent, job.parent)
            if isinstance(error, OSError):
                raise _failure(error, INSTALL_FAILED) from None
            raise
        delete_tree(previous)
        delete_tree(job)
        _remove_if_empty(previous.parent, job.parent)
        return InstallResult(pack.id, pack.version, kind)  # type: ignore[arg-type]

    def _check(
        self, pack: PackDefinition, staged: Path, progress: ProgressCallback, cancel: CancelToken
    ) -> None:
        count = len(pack.files)
        progress(JobPhase.CHECK, 0, count)
        for index, item in enumerate(pack.files, 1):
            if cancel.cancelled:
                raise InstallCancelled()
            path = staged / item.path
            if not path.is_file():
                raise InstallFailed(FILE_MISSING.format(path=item.path))
            if path.stat().st_size != item.size:
                raise InstallFailed(FILE_WRONG_SIZE.format(path=item.path))
            if sha256_file(path) != item.sha256:
                raise InstallFailed(FILE_ALTERED.format(path=item.path))
            progress(JobPhase.CHECK, index, count)
        if cancel.cancelled:
            raise InstallCancelled()

    def _swap(
        self,
        pack: PackDefinition,
        job: Path,
        staged: Path,
        previous: Path,
        manifest: Manifest,
        progress: ProgressCallback,
        cancel: CancelToken,
    ) -> None:
        base = self.root / pack.root
        names = owned_names(pack)
        present = [name for name in names if (base / name).exists() or (base / name).is_symlink()]
        total, done = len(present) + len(names), 0
        journal = Journal.create(job, pack, "install")
        try:
            for name in present:
                if cancel.cancelled:
                    raise InstallCancelled()
                journal.append("out", name)
                (previous / name).parent.mkdir(parents=True, exist_ok=True)
                _journal.move_file(base / name, previous / name)
                done += 1
                progress(JobPhase.SWAP, done, total)
            for name in names:
                if cancel.cancelled:
                    raise InstallCancelled()
                journal.append("in", name)
                (base / name).parent.mkdir(parents=True, exist_ok=True)
                _journal.move_file(staged / name, base / name)
                done += 1
                progress(JobPhase.SWAP, done, total)
            if cancel.cancelled:
                raise InstallCancelled()
            save_manifest(job, self.manifest_path)
            manifest.write(self.manifest_path)
            journal.append("commit")
        except Exception:
            self._rollback(journal, pack, job, previous)
            raise

    def _rollback(self, journal: Journal, pack: PackDefinition, job: Path, previous: Path) -> None:
        """Undo the journal; if that fails too, keep staging for ``recover()``."""
        base = self.root / pack.root
        try:
            undo(journal, pack, base, previous)
            restore_manifest(job, self.manifest_path, pack)
            journal.append("undone")  # before any clean-up: never undone a second time
        except Exception:  # noqa: BLE001 - any undo failure leaves the journal for recover()
            raise _UndoFailed() from None
        delete_tree(previous)
        prune_empty(self.models, base, owned_names(pack))

    def remove(self, pack: PackDefinition) -> None:
        """Remove the listed files, the pack file and the records; ``InstallFailed``."""
        manifest = self._manifest().without_pack(pack)
        previous = self._previous(pack)
        base = self.root / pack.root
        job = self._job()
        journal = Journal.create(job, pack, "remove")
        try:
            for name in owned_names(pack):
                if (base / name).exists() or (base / name).is_symlink():
                    journal.append("out", name)
                    (previous / name).parent.mkdir(parents=True, exist_ok=True)
                    _journal.move_file(base / name, previous / name)
            save_manifest(job, self.manifest_path)
            manifest.write(self.manifest_path)
            journal.append("commit")
        except Exception as error:
            self._rollback(journal, pack, job, previous)  # _UndoFailed keeps the journal
            delete_tree(job)
            _remove_if_empty(previous.parent, job.parent)
            if isinstance(error, OSError):
                raise _failure(error, REMOVE_FAILED) from None
            if isinstance(error, PackError):
                raise
            raise InstallFailed(REMOVE_FAILED.format(name=error.__class__.__name__)) from None
        delete_tree(previous)
        delete_tree(job)
        _remove_if_empty(previous.parent, job.parent)
        prune_empty(self.models, base, owned_names(pack))

    def recover(self) -> tuple[str, ...]:
        """Undo or finish interrupted jobs at launch; the pack ids restored or cleaned.

        Raises ``RecoveryFailed`` (an ``InstallFailed``) after every job was tried when some
        could not be recovered: ``recovered`` and ``failed`` name the packs. A failed job
        keeps its journal, blocks new jobs of its pack and is retried at the next launch.
        """
        catalog = self._catalog
        if catalog is None:
            from lianiq.languages import BUILTIN_REGISTRY
            from lianiq.packs.catalog import BUILTIN_CATALOG_PATH

            catalog = PackCatalog.load(BUILTIN_CATALOG_PATH, BUILTIN_REGISTRY)
        return recover_models(
            self.models, self.root, self.manifest_path, catalog, STAGING_DIR, PREVIOUS_DIR
        )


def _remove_if_empty(*folders: Path) -> None:
    for folder in folders:
        try:
            folder.rmdir()
        except OSError:
            pass
