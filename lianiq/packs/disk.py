"""Disk space of pack jobs (CAP-0171 contract.md §8). Qt-free, standard library only."""

from __future__ import annotations

import shutil
from pathlib import Path

from lianiq.packs.catalog import PackDefinition

HEADROOM_BYTES = 100 * 1024 * 1024


def required_bytes(pack: PackDefinition) -> int:
    """Installed size, plus the archive while it is extracted, plus 100 MiB headroom."""
    archive = pack.archive.size if pack.archive is not None else 0
    return pack.installed_bytes + archive + HEADROOM_BYTES


def free_bytes(models_dir: Path) -> int:
    """Free bytes on the drive of ``models_dir``, or of its nearest existing parent."""
    folder = Path(models_dir).resolve()
    while not folder.exists() and folder.parent != folder:
        folder = folder.parent
    return shutil.disk_usage(folder).free
