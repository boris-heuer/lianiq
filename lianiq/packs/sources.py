"""Download and import sources (CAP-0171 contract.md §5). Qt-free, standard library only.

A source fills a staging folder with the listed files of one catalog pack, under their
catalog paths and nothing else; the installer then checks and swaps them in. Downloads use
``urllib.request`` with the system proxy and HTTPS only, also for every redirect. The pinned
sherpa voice arrives as an archive: only its listed regular members below ``top_level``
are taken, with no links, no duplicates and at most 512 MiB per member (the rules of the
earlier ``scripts/download_models.py``, moved here).
"""

from __future__ import annotations

import http.client
import tarfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import BinaryIO, Literal, Protocol
from urllib.parse import urlsplit

from lianiq.packs.catalog import PackArchive, PackDefinition
from lianiq.packs.errors import ConnectionUnavailable, InstallFailed
from lianiq.packs.import_source import ImportSource
from lianiq.packs.jobs import CancelToken, JobPhase, ProgressCallback
from lianiq.packs.pack_file import ARCHIVE_UNREADABLE, FILE_MISSING
from lianiq.packs.transfer import BLOCK_BYTES, copy_verified
from lianiq.packs.verify import sha256_file

__all__ = [
    "BLOCK_BYTES",
    "DownloadSource",
    "HttpsOnlyRedirects",
    "HttpsTransport",
    "ImportSource",
    "Transport",
]

TIMEOUT_SECONDS = 60.0
MAX_EXTRACTED_FILE_BYTES = 512 * 1024 * 1024
ARCHIVE_PART = "archive.part"  # next to the staged pack folder, inside the job folder
HTTPS_ONLY = "only HTTPS downloads are allowed"
REDIRECT_NOT_HTTPS = "a download was redirected to a non-HTTPS address (HTTPS only)"
HTTP_STATUS = "the download from {host} failed (HTTP {status})"
ARCHIVE_MEMBER_INVALID = "archive member {path} is not a single regular file"
ARCHIVE_MEMBER_TOO_LARGE = "archive member {path} is too large"


class Transport(Protocol):
    def open(self, url: str, timeout: float) -> BinaryIO: ...  # ConnectionUnavailable(host)


class HttpsOnlyRedirects(urllib.request.HTTPRedirectHandler):
    """Follows redirects only to HTTPS addresses."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urlsplit(newurl).scheme != "https":
            raise InstallFailed(REDIRECT_NOT_HTTPS)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class HttpsTransport:
    """``urllib.request`` with the system proxy (``ProxyHandler``) and HTTPS only."""

    def __init__(self) -> None:
        self._opener = urllib.request.build_opener(HttpsOnlyRedirects())

    def open(self, url: str, timeout: float) -> BinaryIO:
        parts = urlsplit(url)
        host = parts.hostname or ""
        if parts.scheme != "https":
            raise InstallFailed(HTTPS_ONLY)
        request = urllib.request.Request(url, headers={"User-Agent": "Lianiq"})
        try:
            return self._opener.open(request, timeout=timeout)
        except urllib.error.HTTPError as error:
            status = error.code
            error.close()
            raise InstallFailed(HTTP_STATUS.format(host=host, status=status)) from None
        except (urllib.error.URLError, OSError, http.client.HTTPException):
            raise ConnectionUnavailable(host) from None


def _https(url: str | None) -> str:
    if url is None or urlsplit(url).scheme != "https":
        raise InstallFailed(HTTPS_ONLY)
    return url


def fetch_archive(
    archive: PackArchive,
    transport: Transport,
    target: Path,
    progress: ProgressCallback,
    cancel: CancelToken,
) -> None:
    """Stream the pinned archive to ``target``; fail on any size or SHA-256 difference."""
    stream = transport.open(_https(archive.url), TIMEOUT_SECONDS)
    copy_verified(
        stream,
        target,
        name=Path(urlsplit(archive.url).path).name,
        size=archive.size,
        sha256=archive.sha256,
        cancel=cancel,
        on_block=lambda received: progress(JobPhase.TRANSFER, received, archive.size),
    )


def extract_archive(
    pack: PackDefinition, archive_path: Path, staging: Path, cancel: CancelToken
) -> None:
    """Extract the listed regular members of ``pack.archive`` into ``staging``.

    Members are matched by ``<top_level>/<listed path>``; each is written under its listed
    catalog path, never under a member name.
    """
    archive = pack.archive
    if archive is None:
        raise ValueError(f"{pack.id} has no archive")
    if sha256_file(archive_path) != archive.sha256:
        raise InstallFailed(ARCHIVE_UNREADABLE)
    wanted = {f"{archive.top_level}/{item.path}": item for item in pack.files}
    found: set[str] = set()
    try:
        with tarfile.open(archive_path, mode="r:*") as bundle:
            for member in bundle:
                item = wanted.get(member.name)
                if item is None:
                    continue
                if not member.isreg() or member.name in found:
                    raise InstallFailed(ARCHIVE_MEMBER_INVALID.format(path=item.path))
                if member.size > MAX_EXTRACTED_FILE_BYTES:
                    raise InstallFailed(ARCHIVE_MEMBER_TOO_LARGE.format(path=item.path))
                stream = bundle.extractfile(member)
                if stream is None:
                    raise InstallFailed(ARCHIVE_MEMBER_INVALID.format(path=item.path))
                copy_verified(
                    stream,
                    staging / item.path,
                    name=item.path,
                    size=item.size,
                    sha256=item.sha256,
                    cancel=cancel,
                )
                found.add(member.name)
    except (tarfile.TarError, EOFError, OSError):
        raise InstallFailed(ARCHIVE_UNREADABLE) from None
    for name, item in wanted.items():
        if name not in found:
            raise InstallFailed(FILE_MISSING.format(path=item.path))


class DownloadSource:
    """Fetches a pack from its pinned HTTPS URLs through an injected ``Transport``."""

    def __init__(
        self,
        transport: Transport,
        *,
        record_source: Literal["download", "script"] = "download",
    ) -> None:
        self.transport = transport
        self.record_source = record_source

    def fetch(
        self,
        pack: PackDefinition,
        staging: Path,
        progress: ProgressCallback,
        cancel: CancelToken,
    ) -> None:
        if pack.archive is not None:
            part = staging.parent / ARCHIVE_PART
            try:
                fetch_archive(pack.archive, self.transport, part, progress, cancel)
                extract_archive(pack, part, staging, cancel)
            finally:
                part.unlink(missing_ok=True)
            return
        urls = [_https(item.url) for item in pack.files]
        total, done = pack.download_bytes, 0
        for item, url in zip(pack.files, urls, strict=True):
            stream = self.transport.open(url, TIMEOUT_SECONDS)
            base = done
            copy_verified(
                stream,
                staging / item.path,
                name=item.path,
                size=item.size,
                sha256=item.sha256,
                cancel=cancel,
                on_block=lambda received, base=base: progress(
                    JobPhase.TRANSFER, base + received, total
                ),
            )
            done += item.size
