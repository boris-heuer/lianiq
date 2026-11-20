"""Verified streaming copies (CAP-0171 contract.md §5). Qt-free, standard library only.

Bytes are untrusted until they match: a copy reads 1 MiB blocks, stops as soon as more
bytes arrive than the pinned size, hashes while it streams, checks the cancel token between
blocks and deletes its partial target on any failure.
"""

from __future__ import annotations

import hashlib
import http.client
from collections.abc import Callable
from pathlib import Path
from typing import BinaryIO

from lianiq.packs.errors import InstallCancelled, InstallFailed
from lianiq.packs.jobs import CancelToken
from lianiq.packs.pack_file import FILE_ALTERED, FILE_WRONG_SIZE

BLOCK_BYTES = 1024 * 1024
TRANSFER_FAILED = "transfer of {path} failed"

ErrorFactory = Callable[[str], Exception]


def copy_verified(
    source: BinaryIO,
    target: Path,
    *,
    name: str,
    size: int,
    sha256: str,
    cancel: CancelToken,
    on_block: Callable[[int], None] | None = None,
    error: ErrorFactory = InstallFailed,
    read_failed: str = TRANSFER_FAILED,
) -> None:
    """Stream ``source`` to ``target`` and require exactly ``size`` bytes with ``sha256``.

    ``name`` is the listed path used in reasons; ``on_block`` receives the bytes received so
    far; ``error`` builds the exception for a reason (``InstallFailed`` or ``PackFileError``).
    """
    digest = hashlib.sha256()
    received = 0
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with target.open("wb") as out:
            while True:
                if cancel.cancelled:
                    raise InstallCancelled()
                try:
                    block = source.read(BLOCK_BYTES)
                except (OSError, http.client.HTTPException, EOFError):
                    raise error(read_failed.format(path=name)) from None
                if not block:
                    break
                received += len(block)
                if received > size:
                    raise error(FILE_WRONG_SIZE.format(path=name))
                digest.update(block)
                out.write(block)
                if on_block is not None:
                    on_block(received)
        if received != size:
            raise error(FILE_WRONG_SIZE.format(path=name))
        if digest.hexdigest() != sha256:
            raise error(FILE_ALTERED.format(path=name))
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    finally:
        source.close()
