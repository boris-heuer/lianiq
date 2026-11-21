"""Fakes and builders for the CAP-0171 installer tests (contract.md §5, §6). No network.

``FakeTransport`` serves pinned bytes by URL; ``builtin_shaped`` turns the built-in catalog
into one with the same ids, roots, listed paths and URLs but a few bytes per file, so every
catalog pack can be installed for real in a temporary project.
"""

from __future__ import annotations

import hashlib
import io
import json
import tarfile
import zipfile
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from _pack_fixtures import capability_catalog, pack_entry, sha, write_catalog

from lianiq.config import AppConfig
from lianiq.languages import BUILTIN_REGISTRY
from lianiq.packs import journal as journal_module
from lianiq.packs.catalog import BUILTIN_CATALOG_PATH, PackCatalog, PackDefinition
from lianiq.packs.errors import ConnectionUnavailable
from lianiq.packs.installer import PackInstaller
from lianiq.packs.jobs import CancelToken, JobPhase
from lianiq.packs.manifest import Manifest
from lianiq.packs.pack_file import PACK_FILE_NAME, render_pack_file
from lianiq.packs.sources import DownloadSource
from lianiq.packs.state import pack_status

MANIFEST = "models/model-manifest.json"
NOW = datetime(2026, 11, 20, 9, 0, 0, tzinfo=UTC)
ACCEPTED = datetime(2026, 11, 20, 8, 59, 0, tzinfo=UTC)
MT_V1 = {"pytorch_model.bin": b"weights v1", "config.json": b'{"v": 1}', "sub/vocab.json": b"{}"}
MT_V2 = {"pytorch_model.bin": b"weights v2!", "config.json": b'{"v": 2}', "sub/vocab.json": b"{}"}
ARCHIVE_FILES = {"model.onnx": b"sherpa model", "tokens.txt": b"a 1\nb 2\n"}
ARCHIVE_TOP = "vits-test"
ARCHIVE_URL = "https://archive.example.test/voice.tar.bz2"


def url_of(pack_id: str, path: str) -> str:
    return f"https://files.example.test/{pack_id}/{path}"


def mt_pack_entry(version: str = "1", files: Mapping[str, bytes] = MT_V1) -> dict[str, Any]:
    entry = pack_entry(
        "mt-a", "translation", ["de>zh-Hans"], "models/opus-mt-de-zh", files, version=version
    )
    for item in entry["files"]:
        item["url"] = url_of("mt-a", item["path"])
    return entry


def tar_bytes(members: Mapping[str, bytes], *, symlink: str | None = None) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:bz2") as bundle:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            bundle.addfile(info, io.BytesIO(data))
        if symlink is not None:
            info = tarfile.TarInfo(symlink)
            info.type = tarfile.SYMTYPE
            info.linkname = "../../outside"
            bundle.addfile(info)
    return buffer.getvalue()


def archive_tar(extra: Mapping[str, bytes] | None = None) -> bytes:
    members = {f"{ARCHIVE_TOP}/{name}": data for name, data in ARCHIVE_FILES.items()}
    return tar_bytes({**members, **(extra or {})})


def archive_pack_entry(payload: bytes) -> dict[str, Any]:
    archive = {
        "url": ARCHIVE_URL,
        "size": len(payload),
        "sha256": sha(payload),
        "top_level": ARCHIVE_TOP,
    }
    return pack_entry(
        "tts-z",
        "voice",
        ["zh-Hans"],
        "models/sherpa/vits-icefall-zh-aishell3",
        ARCHIVE_FILES,
        archive=archive,
    )


def catalog_of(folder: Path, *entries: dict[str, Any], name: str = "catalog.json"):
    return PackCatalog.load(write_catalog(folder / name, list(entries)), BUILTIN_REGISTRY)


class FakeTransport:
    """``Transport`` over in-memory payloads; records every URL it opens."""

    def __init__(
        self,
        payloads: Mapping[str, bytes],
        *,
        unavailable: frozenset[str] = frozenset(),
        broken: Mapping[str, int] | None = None,
        on_read: Callable[[str, int], None] | None = None,
    ) -> None:
        self.payloads = dict(payloads)
        self.unavailable = unavailable
        self.broken = dict(broken or {})  # url -> bytes served before an OSError
        self.on_read = on_read
        self.opened: list[str] = []

    def open(self, url: str, timeout: float) -> io.BufferedIOBase:
        self.opened.append(url)
        host = urlsplit(url).hostname or url
        if host in self.unavailable:
            raise ConnectionUnavailable(host)
        return _Stream(self, url, self.payloads[url])


class _Stream(io.BytesIO):
    def __init__(self, transport: FakeTransport, url: str, data: bytes) -> None:
        super().__init__(data)
        self._transport, self._url = transport, url

    def read(self, size: int | None = -1) -> bytes:
        limit = self._transport.broken.get(self._url)
        if limit is not None and self.tell() >= limit:
            raise ConnectionResetError("connection reset")
        if self._transport.on_read is not None:
            self._transport.on_read(self._url, self.tell())
        return super().read(size)


def payloads_for(pack: PackDefinition, files: Mapping[str, bytes]) -> dict[str, bytes]:
    return {item.url: files[item.path] for item in pack.files if item.url is not None}


class Progress:
    def __init__(self) -> None:
        self.calls: list[tuple[JobPhase, int, int]] = []

    def __call__(self, phase: JobPhase, done: int, total: int) -> None:
        self.calls.append((phase, done, total))

    def phases(self) -> list[JobPhase]:
        seen: list[JobPhase] = []
        for phase, _, _ in self.calls:
            if not seen or seen[-1] is not phase:
                seen.append(phase)
        return seen


def installer(project: Path, catalog: PackCatalog | None = None, **kwargs: Any) -> PackInstaller:
    return PackInstaller(project, project / MANIFEST, lambda: NOW, catalog=catalog, **kwargs)


def tree(folder: Path) -> dict[str, bytes]:
    """Every file below ``folder`` by POSIX path, for before/after comparisons."""
    if not folder.exists():
        return {}
    return {
        path.relative_to(folder).as_posix(): path.read_bytes()
        for path in sorted(folder.rglob("*"))
        if path.is_file()
    }


def pack_folder(folder: Path, pack: PackDefinition, files: Mapping[str, bytes]) -> Path:
    """An import folder: the pack file, every listed file and one unlisted extra."""
    for name, data in files.items():
        target = folder / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    (folder / PACK_FILE_NAME).write_bytes(render_pack_file(pack))
    (folder / "extra-notes.txt").write_bytes(b"not listed")
    return folder


def pack_zip(
    path: Path,
    pack: PackDefinition | None,
    files: Mapping[str, bytes],
    *,
    extra: Mapping[str, bytes] | None = None,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as bundle:
        if pack is not None:
            bundle.writestr(PACK_FILE_NAME, render_pack_file(pack))
        for name, data in {**files, "extra-notes.txt": b"not listed", **(extra or {})}.items():
            bundle.writestr(name, data)
    return path


def builtin_shaped(folder: Path) -> tuple[PackCatalog, dict[str, bytes], dict[str, dict]]:
    """The built-in catalog with tiny synthetic bytes: (catalog, payloads by URL, files)."""
    raw = json.loads(BUILTIN_CATALOG_PATH.read_text(encoding="utf-8"))
    payloads: dict[str, bytes] = {}
    contents: dict[str, dict[str, bytes]] = {}
    for entry in raw["packs"]:
        files = {item["path"]: f"{entry['id']}/{item['path']}".encode() for item in entry["files"]}
        contents[entry["id"]] = files
        for item in entry["files"]:
            item["size"], item["sha256"] = len(files[item["path"]]), sha(files[item["path"]])
            if item["url"] is not None:
                payloads[item["url"]] = files[item["path"]]
        if entry["archive"] is not None:
            top = entry["archive"]["top_level"]
            data = tar_bytes({f"{top}/{name}": value for name, value in files.items()})
            entry["archive"].update(size=len(data), sha256=hashlib.sha256(data).hexdigest())
            payloads[entry["archive"]["url"]] = data
    path = folder / "builtin-shaped.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(raw), encoding="utf-8")
    return PackCatalog.load(path, BUILTIN_REGISTRY), payloads, contents


def download(
    project: Path, packs, files, *, progress=None, cancel=None, transport=None, pack_id="mt-a"
):
    """Install ``pack_id`` from ``packs`` through ``DownloadSource`` and a fake transport."""
    pack = packs.get(pack_id)
    source = DownloadSource(transport or FakeTransport(payloads_for(pack, files)))
    return installer(project, packs).install(
        pack, source, ACCEPTED, progress or Progress(), cancel or CancelToken()
    )


def state(project: Path, packs, pack_id: str = "mt-a"):
    manifest = Manifest.read(project / MANIFEST)
    catalog = capability_catalog(project, packs, manifest)
    return pack_status(packs.get(pack_id), catalog, manifest, AppConfig(), None, None)


def models_scratch(project: Path) -> list[str]:
    if not (project / "models").is_dir():
        return []
    return sorted(p.name for p in (project / "models").iterdir() if p.name.startswith(".lianiq"))


class Fault:
    """``move_file`` that fails once at call ``at`` (1-based); later calls move normally."""

    def __init__(self, monkeypatch, at: int, error: BaseException) -> None:
        self.calls, self.at, self.error = 0, at, error
        self._move = journal_module.move_file
        monkeypatch.setattr(journal_module, "move_file", self)

    def __call__(self, source: Path, target: Path) -> None:
        self.calls += 1
        if self.calls == self.at:
            raise self.error
        self._move(source, target)
