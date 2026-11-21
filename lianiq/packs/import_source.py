"""Import of a pack from a folder or a ``.zip`` (CAP-0171 contract.md §2, §5). Qt-free.

The source root must hold ``lianiq-pack.json`` and every listed file. The pack file must
match the catalog entry (``check_against``); then exactly the catalog entry's listed files
are copied, read from the source under their catalog paths and verified while they stream.
Unlisted files are ignored. Links and unsafe member names reject the whole source; every
rejection is a ``PackFileError`` with its contract.md §2 reason. No network is used.
"""

from __future__ import annotations

import stat
import zipfile
import zlib
from pathlib import Path
from typing import BinaryIO, Literal

from lianiq.packs.catalog import PackDefinition
from lianiq.packs.errors import PackFileError
from lianiq.packs.jobs import CancelToken, JobPhase, ProgressCallback
from lianiq.packs.pack_file import (
    ARCHIVE_UNREADABLE,
    FILE_MISSING,
    FILE_WRONG_SIZE,
    NO_PACK_FILE,
    PACK_FILE_NAME,
    UNSAFE_PATH,
    check_against,
    parse_pack_file,
)
from lianiq.packs.paths import is_safe_relative
from lianiq.packs.transfer import copy_verified

MAX_PACK_FILE_BYTES = 1024 * 1024
_ZIP_ERRORS = (zipfile.BadZipFile, zlib.error, RuntimeError, NotImplementedError, EOFError)


class _Folder:
    def __init__(self, root: Path) -> None:
        self.root = root

    def _path(self, name: str) -> Path:
        candidate = self.root
        for part in name.split("/"):
            candidate = candidate / part
            if candidate.is_symlink() or candidate.is_junction():
                raise PackFileError(UNSAFE_PATH.format(path=name))
        return candidate

    def size(self, name: str) -> int | None:
        path = self._path(name)
        return path.stat().st_size if path.is_file() else None

    def open(self, name: str) -> BinaryIO:
        return self._path(name).open("rb")

    def close(self) -> None:
        pass


class _Zip:
    def __init__(self, path: Path) -> None:
        try:
            self.bundle = zipfile.ZipFile(path)
            infos = self.bundle.infolist()
        except (*_ZIP_ERRORS, OSError):
            raise PackFileError(ARCHIVE_UNREADABLE) from None
        self.members: dict[str, zipfile.ZipInfo] = {}
        try:
            for info in infos:
                name = info.filename[:-1] if info.is_dir() else info.filename
                if not is_safe_relative(name):
                    raise PackFileError(UNSAFE_PATH.format(path=info.filename))
                if stat.S_ISLNK(info.external_attr >> 16):
                    raise PackFileError(UNSAFE_PATH.format(path=name))
                if not info.is_dir() and name in self.members:
                    raise PackFileError(ARCHIVE_UNREADABLE)
                if not info.is_dir():
                    self.members[name] = info
        except PackFileError:
            self.bundle.close()
            raise

    def size(self, name: str) -> int | None:
        info = self.members.get(name)
        return None if info is None else info.file_size

    def open(self, name: str) -> BinaryIO:
        try:
            return self.bundle.open(self.members[name])  # type: ignore[return-value]
        except _ZIP_ERRORS:
            raise PackFileError(ARCHIVE_UNREADABLE) from None

    def close(self) -> None:
        self.bundle.close()


def _reader(path: Path) -> _Folder | _Zip:
    if path.is_dir():
        return _Folder(path)
    if path.is_file():
        return _Zip(path)
    raise PackFileError(NO_PACK_FILE)


class ImportSource:
    """A user-chosen folder or ``.zip`` holding one pack (``source: import``)."""

    record_source: Literal["import"] = "import"

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def fetch(
        self,
        pack: PackDefinition,
        staging: Path,
        progress: ProgressCallback,
        cancel: CancelToken,
    ) -> None:
        reader = _reader(self.path)
        try:
            self._copy(reader, pack, staging, progress, cancel)
        finally:
            reader.close()

    @staticmethod
    def _pack_file(reader: _Folder | _Zip) -> bytes:
        size = reader.size(PACK_FILE_NAME)
        if size is None or size > MAX_PACK_FILE_BYTES:
            raise PackFileError(NO_PACK_FILE)
        try:
            with reader.open(PACK_FILE_NAME) as stream:
                return stream.read(MAX_PACK_FILE_BYTES + 1)
        except (OSError, *_ZIP_ERRORS):
            raise PackFileError(NO_PACK_FILE) from None

    def _copy(
        self,
        reader: _Folder | _Zip,
        pack: PackDefinition,
        staging: Path,
        progress: ProgressCallback,
        cancel: CancelToken,
    ) -> None:
        check_against(parse_pack_file(self._pack_file(reader)), pack)
        total, done = pack.installed_bytes, 0
        for item in pack.files:  # the catalog entry, never the pack file document
            size = reader.size(item.path)
            if size is None:
                raise PackFileError(FILE_MISSING.format(path=item.path))
            if size != item.size:
                raise PackFileError(FILE_WRONG_SIZE.format(path=item.path))
            unreadable = ARCHIVE_UNREADABLE if isinstance(reader, _Zip) else FILE_MISSING
            try:
                stream = reader.open(item.path)
            except OSError:
                raise PackFileError(FILE_MISSING.format(path=item.path)) from None
            base = done
            try:
                copy_verified(
                    stream,
                    staging / item.path,
                    name=item.path,
                    size=item.size,
                    sha256=item.sha256,
                    cancel=cancel,
                    on_block=lambda got, base=base: progress(JobPhase.TRANSFER, base + got, total),
                    error=PackFileError,
                    read_failed=unreadable,
                )
            except _ZIP_ERRORS:
                raise PackFileError(ARCHIVE_UNREADABLE) from None
            done += item.size
