"""The swap journal of pack jobs (CAP-0171 contract.md §5). Qt-free, standard library only.

Before each file move of a swap or remove the job appends the move (``out`` or ``in`` and
the listed path) to ``models/.lianiq-staging/<uuid>/journal.json`` and syncs it to disk; a
``commit`` entry follows the manifest write. Undo replays the moves in reverse: moved-in
files are deleted, moved-out files are moved back; an ``undone`` entry follows a successful
undo before any clean-up, so a journal is never undone twice. Undo is also safe to repeat
after a partial run: it never deletes a moved-in path whose moved-out copy is already back. Every path undo touches is derived from
the catalog entry (pack root plus listed files); a journal path that is not one of them is
ignored, so neither a journal nor a pack-file document can name a path to write or remove.
"""

from __future__ import annotations

import json
import os
import shutil
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lianiq.packs.catalog import PackDefinition
from lianiq.packs.errors import ManifestError
from lianiq.packs.manifest import Manifest
from lianiq.packs.pack_file import PACK_FILE_NAME

JOURNAL_FORMAT = "lianiq-swap-journal/v1"
JOURNAL_NAME = "journal.json"
MANIFEST_BACKUP = "manifest.before"
MANIFEST_ABSENT = "manifest.absent"
MOVES = ("out", "in")


def move_file(source: Path, target: Path) -> None:
    """One rename of a swap; tests replace it to inject failures and crashes."""
    os.replace(source, target)


def delete_tree(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


def owned_names(pack: PackDefinition) -> tuple[str, ...]:
    """The catalog paths a job may move: every listed file, then the pack file."""
    return (*(item.path for item in pack.files), PACK_FILE_NAME)


def _sync_write(path: Path, data: bytes) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


@dataclass
class Journal:
    path: Path
    pack_id: str
    version: str
    operation: str  # "install" or "remove"
    entries: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def create(cls, folder: Path, pack: PackDefinition, operation: str) -> Journal:
        journal = cls(folder / JOURNAL_NAME, pack.id, pack.version, operation)
        journal._write()
        return journal

    @classmethod
    def read(cls, folder: Path) -> Journal | None:
        """The journal of a staging folder, or ``None`` when absent or unreadable."""
        path = folder / JOURNAL_NAME
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return None
        if not isinstance(raw, dict) or raw.get("format") != JOURNAL_FORMAT:
            return None
        entries = raw.get("entries")
        texts = [raw.get(key) for key in ("pack_id", "version", "operation")]
        if not isinstance(entries, list) or not all(isinstance(t, str) for t in texts):
            return None
        valid = [item for item in entries if isinstance(item, dict)]
        return cls(path, texts[0], texts[1], texts[2], valid)  # type: ignore[arg-type]

    @property
    def committed(self) -> bool:
        return any(item.get("op") == "commit" for item in self.entries)

    @property
    def undone(self) -> bool:
        return any(item.get("op") == "undone" for item in self.entries)

    @property
    def finished(self) -> bool:
        """Committed or undone: only clean-up remains, never another undo."""
        return self.committed or self.undone

    def append(self, op: str, path: str | None = None) -> None:
        """Record a move (``out``/``in`` with its path), ``commit`` or ``undone``; fsync."""
        self.entries.append({"op": op} if path is None else {"op": op, "path": path})
        self._write()

    def _write(self) -> None:
        payload = {
            "format": JOURNAL_FORMAT,
            "pack_id": self.pack_id,
            "version": self.version,
            "operation": self.operation,
            "entries": self.entries,
        }
        _sync_write(self.path, (json.dumps(payload, indent=2) + "\n").encode("utf-8"))

    def moves(self, pack: PackDefinition) -> list[tuple[str, str]]:
        """The recorded moves whose path is a catalog path of ``pack``, in order."""
        allowed = set(owned_names(pack))
        return [
            (item["op"], item["path"])
            for item in self.entries
            if item.get("op") in MOVES and item.get("path") in allowed
        ]


def undo(journal: Journal, pack: PackDefinition, base: Path, previous: Path) -> None:
    """Reverse every recorded move: delete moved-in files, move moved-out files back.

    A moved-in path that was also moved out is deleted only while its moved-out copy is
    still in ``previous``; otherwise the file in the root is the restored original.
    """
    moves = journal.moves(pack)
    moved_out = {name for op, name in moves if op == "out"}
    for op, name in reversed(moves):
        target = base / name
        if op == "in":
            kept = previous / name
            if name in moved_out and not (kept.exists() or kept.is_symlink()):
                continue
            if target.is_file() or target.is_symlink():
                target.unlink()
            continue
        kept = previous / name
        if kept.exists() or kept.is_symlink():
            target.parent.mkdir(parents=True, exist_ok=True)
            move_file(kept, target)


def save_manifest(folder: Path, manifest_path: Path) -> None:
    """Keep the manifest as it was before the job's manifest write, for undo after a crash."""
    if manifest_path.is_file():
        _sync_write(folder / MANIFEST_BACKUP, manifest_path.read_bytes())
    else:
        _sync_write(folder / MANIFEST_ABSENT, b"")


def _owned_records(manifest: Manifest, pack: PackDefinition) -> Manifest:
    """Only the artifact records and ``packs[]`` record of ``pack`` from ``manifest``."""
    paths = {f"{pack.root}/{name}" for name in owned_names(pack)}
    artifacts = [
        item
        for item in manifest.artifacts
        if item.get("pack_id") == pack.id or item.get("path") in paths
    ]
    record = manifest.pack(pack.id)
    return Manifest(artifacts, [] if record is None else [record])


def restore_manifest(folder: Path, manifest_path: Path, pack: PackDefinition) -> None:
    """Put back ``pack``'s records as they were before the job; other packs keep theirs."""
    backup, absent = folder / MANIFEST_BACKUP, folder / MANIFEST_ABSENT
    if not backup.is_file() and not absent.is_file():
        return  # the job never reached its manifest write
    before = Manifest()
    if backup.is_file():
        try:
            before = Manifest.read(backup)
        except ManifestError:
            _sync_write(manifest_path, backup.read_bytes())
            return
    whole = Manifest.read(manifest_path)
    old, now = _owned_records(before, pack), _owned_records(whole, pack)
    if (old.artifacts, old.packs) == (now.artifacts, now.packs):
        return  # the manifest write never happened, or wrote the same records
    current = whole.without_pack(pack)
    extra = current._extra  # same package: keep unknown top-level fields as they are
    artifacts, packs = [*current.artifacts, *old.artifacts], [*current.packs, *old.packs]
    Manifest(artifacts, packs, extra).write(manifest_path)


def unfinished_job(staging: Path, pack_id: str) -> bool:
    """Whether a staging job of ``pack_id`` holds a journal that is neither committed nor undone."""
    if not staging.is_dir():
        return False
    for job in staging.iterdir():
        journal = Journal.read(job) if job.is_dir() else None
        if journal is not None and journal.pack_id == pack_id and not journal.finished:
            return True
    return False


def prune_empty(models: Path, base: Path, names: Iterable[str]) -> None:
    """Delete empty folders of the listed paths, the root and its parents below ``models``."""
    folders = {(base / name).parent for name in names} | {base}
    for folder in sorted(folders, key=lambda path: len(path.parts), reverse=True):
        current = folder
        while current != models and models in current.parents:
            try:
                current.rmdir()
            except OSError:
                break
            current = current.parent
