"""Digests of listed pack files (CAP-0171 contract.md §4 ``PackVerifier``). Qt-free.

Hashing is lazy: nothing is hashed until a caller asks, and a digest is cached by (resolved
path, size, mtime). The caller decides the thread; the page and the readiness review call
it on a worker thread after a manifest load or a job, never at launch. This module imports
nothing from ``lianiq`` at run time, so ``lianiq.languages`` can use it without a cycle.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lianiq.packs.catalog import PackFile

BLOCK_BYTES = 1024 * 1024


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(BLOCK_BYTES), b""):
            digest.update(block)
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class FileReport:
    """Listed files (by their listed path) that are absent, of the wrong size or altered."""

    missing: tuple[str, ...] = ()
    wrong_size: tuple[str, ...] = ()
    altered: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not (self.missing or self.wrong_size or self.altered)


class PackVerifier:
    def __init__(self, hash_file: Callable[[Path], str] | None = None) -> None:
        self._hash_file = hash_file or sha256_file
        self._digests: dict[tuple[str, int, int], str] = {}

    def digest(self, path: Path) -> str:
        stat = path.stat()
        key = (str(path.resolve()), stat.st_size, stat.st_mtime_ns)
        cached = self._digests.get(key)
        if cached is None:
            cached = self._hash_file(path)
            self._digests[key] = cached
        return cached

    def invalidate(self) -> None:
        self._digests.clear()

    def inspect(
        self,
        base: Path,
        files: Iterable[PackFile],
        expected: Mapping[str, str] | None = None,
        *,
        digests: bool = True,
    ) -> FileReport:
        """Check each listed file below ``base``: presence, exact size, then SHA-256.

        ``expected`` maps a listed path to its manifest digest, which then counts instead
        of the listed digest. Only present files of the right size are hashed.
        """
        missing: list[str] = []
        wrong_size: list[str] = []
        altered: list[str] = []
        for item in files:
            path = base / item.path
            if not path.is_file():
                missing.append(item.path)
            elif path.stat().st_size != item.size:
                wrong_size.append(item.path)
            elif digests:
                want = (expected or {}).get(item.path, item.sha256).lower()
                if self.digest(path) != want:
                    altered.append(item.path)
        return FileReport(tuple(missing), tuple(wrong_size), tuple(altered))
