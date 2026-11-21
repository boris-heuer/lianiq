"""Launch recovery of interrupted pack jobs (CAP-0171 contract.md §5 ``recover()``). Qt-free.

For each staging folder: a journal without ``commit`` is undone (moved-in files deleted,
moved-out files moved back) and the manifest is restored to its state before the job; a
committed journal only needs its clean-up (and, for a remove, the empty root deleted).
Then the staging folder and the pack's ``.lianiq-previous`` folder are deleted. A previous
folder without a journal is moved back when the manifest does not match the root, else
deleted. Only catalog packs are touched, and only at their catalog paths.
"""

from __future__ import annotations

import logging
from pathlib import Path

from lianiq.packs import journal as _journal
from lianiq.packs.catalog import PackCatalog, PackDefinition
from lianiq.packs.errors import InstallFailed, ManifestError, UnknownPackError
from lianiq.packs.journal import (
    Journal,
    delete_tree,
    owned_names,
    prune_empty,
    restore_manifest,
    undo,
)
from lianiq.packs.manifest import Manifest
from lianiq.packs.verify import sha256_file

_LOG = logging.getLogger("lianiq.packs.recovery")
RECOVERY_FAILED = "{count} interrupted pack jobs could not be recovered; they are retried at launch"


class RecoveryFailed(InstallFailed):
    """``recover()`` tried every job; ``failed`` packs keep their journal for the next launch.

    WI-03 start-up catches it, logs nothing further (the failures are already logged with the
    AC-27 fields) and continues: ``recovered`` were restored or cleaned, ``failed`` stay
    blocked for install, update and remove (``NOT_RECOVERED``) until a later launch succeeds.
    """

    def __init__(self, recovered: tuple[str, ...], failed: tuple[str, ...]) -> None:
        super().__init__(RECOVERY_FAILED.format(count=len(failed)))
        self.recovered = recovered
        self.failed = failed


def _pack(catalog: PackCatalog, pack_id: str) -> PackDefinition | None:
    try:
        return catalog.get(pack_id)
    except UnknownPackError:
        return None


def _children(folder: Path) -> list[Path]:
    return sorted(path for path in folder.iterdir()) if folder.is_dir() else []


def _matches(pack: PackDefinition, root: Path, manifest_path: Path) -> bool:
    """Whether the manifest records the pack and every recorded file in its root matches."""
    try:
        manifest = Manifest.read(manifest_path)
    except ManifestError:
        return False
    if manifest.pack(pack.id) is None:
        return False
    digests = manifest.digests()
    for name in owned_names(pack):
        expected = digests.get(f"{pack.root}/{name}")
        path = root / pack.root / name
        if expected is None or not path.is_file() or sha256_file(path) != expected:
            return False
    return True


def _move_back(pack: PackDefinition, root: Path, previous: Path) -> None:
    base = root / pack.root
    for name in owned_names(pack):  # catalog paths only; anything else is deleted below
        kept = previous / name
        if kept.is_file():
            (base / name).parent.mkdir(parents=True, exist_ok=True)
            _journal.move_file(kept, base / name)


def _discard(path: Path) -> None:
    if path.is_dir():
        delete_tree(path)
    else:
        path.unlink(missing_ok=True)


def _log_failure(pack_id: str, version: str, operation: str, error: Exception) -> None:
    _LOG.warning(
        "pack job pack_id=%s version=%s operation=%s phase=recover state=failed error=%s",
        pack_id,
        version,
        operation,
        error.__class__.__name__,
    )


def _recover_job(
    job: Path,
    journal: Journal,
    pack: PackDefinition,
    models: Path,
    root: Path,
    manifest: Path,
    previous_root: Path,
) -> None:
    base, previous = root / pack.root, previous_root / pack.id
    if not journal.finished:
        undo(journal, pack, base, previous)
        restore_manifest(job, manifest, pack)
        journal.append("undone")  # a crash during the clean-up below never undoes it again
    if not journal.committed or journal.operation == "remove":
        prune_empty(models, base, owned_names(pack))
    delete_tree(previous)


def recover_models(
    models: Path,
    root: Path,
    manifest_path: Path,
    catalog: PackCatalog,
    staging_dir: str,
    previous_dir: str,
) -> tuple[str, ...]:
    """Recover every job; ``RecoveryFailed`` after all were tried if some could not be."""
    staging, previous_root = models / staging_dir, models / previous_dir
    touched: list[str] = []
    failed: list[str] = []
    for job in _children(staging):
        journal = Journal.read(job) if job.is_dir() else None
        pack = None if journal is None else _pack(catalog, journal.pack_id)
        if journal is not None and pack is not None:
            try:
                _recover_job(job, journal, pack, models, root, manifest_path, previous_root)
            except Exception as error:  # noqa: BLE001 - contain it; the journal stays
                _log_failure(pack.id, journal.version, journal.operation, error)
                failed.append(pack.id)
                continue
            touched.append(pack.id)
        _discard(job)
    for previous in _children(previous_root):
        pack = _pack(catalog, previous.name)
        if pack is not None and pack.id in failed:
            continue  # its journal still needs these files
        if pack is not None and previous.is_dir():
            try:
                if not _matches(pack, root, manifest_path):
                    _move_back(pack, root, previous)
            except Exception as error:  # noqa: BLE001 - keep the copy for the next launch
                _log_failure(pack.id, pack.version, "recover", error)
                failed.append(pack.id)
                continue
            if pack.id not in touched:
                touched.append(pack.id)
        _discard(previous)
    for folder in (staging, previous_root):
        try:
            folder.rmdir()
        except OSError:
            pass
    if failed:
        raise RecoveryFailed(tuple(touched), tuple(dict.fromkeys(failed)))
    return tuple(touched)
