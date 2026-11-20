"""The ``lianiq-pack.json`` pack file: parse, render, check (CAP-0171 contract.md §2). Qt-free.

Every installed pack and every import source holds this file at its root. Its bytes are
untrusted: a malformed document is ``no pack file``, an unsafe listed path is rejected by
name, and only ``check_against`` the catalog entry makes a document acceptable.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from lianiq.packs.catalog import (
    RESERVED_FILE_NAME,
    PackDefinition,
    PackFile,
    is_safe_relative,
    is_sha256,
    is_size,
)
from lianiq.packs.errors import PackFileError

PACK_FILE_NAME = RESERVED_FILE_NAME  # "lianiq-pack.json"
PACK_FORMAT = "lianiq-pack/v1"

# Rejection reasons (contract.md §2), rendered with PACK_IMPORT_REJECTED.
NO_PACK_FILE = "no pack file"
UNKNOWN_PACK = "unknown pack {id}"
VERSION_NOT_OFFERED = "version {version} is not offered"
FILE_MISSING = "file {path} is missing"
FILE_WRONG_SIZE = "file {path} has the wrong size"
FILE_ALTERED = "file {path} failed the integrity check"
UNSAFE_PATH = "unsafe path {path}"
ARCHIVE_UNREADABLE = "the archive cannot be read"


@dataclass(frozen=True, slots=True)
class PackFileDocument:
    id: str
    version: str
    files: tuple[PackFile, ...]  # url always None here


def _listed(raw: object) -> PackFile:
    if not isinstance(raw, dict) or set(raw) != {"path", "size", "sha256"}:
        raise PackFileError(NO_PACK_FILE)
    path = raw["path"]
    if not isinstance(path, str) or not path:
        raise PackFileError(NO_PACK_FILE)
    if not is_safe_relative(path):
        raise PackFileError(UNSAFE_PATH.format(path=path))
    if not is_size(raw["size"]) or not is_sha256(raw["sha256"]):
        raise PackFileError(NO_PACK_FILE)
    return PackFile(path, raw["size"], raw["sha256"], None)


def parse_pack_file(raw: bytes) -> PackFileDocument:
    try:
        payload: Any = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise PackFileError(NO_PACK_FILE) from None
    if not isinstance(payload, dict) or payload.get("format") != PACK_FORMAT:
        raise PackFileError(NO_PACK_FILE)
    pack_id, version, files = payload.get("id"), payload.get("version"), payload.get("files")
    if not isinstance(pack_id, str) or not pack_id or not isinstance(version, str) or not version:
        raise PackFileError(NO_PACK_FILE)
    if not isinstance(files, list) or not files:
        raise PackFileError(NO_PACK_FILE)
    listed = tuple(_listed(item) for item in files)
    if len({item.path for item in listed}) != len(listed):
        raise PackFileError(NO_PACK_FILE)
    return PackFileDocument(pack_id, version, listed)


def render_pack_file(pack: PackDefinition) -> bytes:
    """The pack file of ``pack``: UTF-8 JSON with sorted keys and a trailing newline."""
    payload = {
        "format": PACK_FORMAT,
        "id": pack.id,
        "version": pack.version,
        "files": [
            {"path": item.path, "size": item.size, "sha256": item.sha256} for item in pack.files
        ],
    }
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")


def check_against(document: PackFileDocument, pack: PackDefinition) -> None:
    """Require the catalog entry's id, version and exact file set (path, size, sha256)."""
    if document.id != pack.id:
        raise PackFileError(UNKNOWN_PACK.format(id=document.id))
    if document.version != pack.version:
        raise PackFileError(VERSION_NOT_OFFERED.format(version=document.version))
    by_path = {item.path: item for item in document.files}
    for expected in pack.files:
        found = by_path.get(expected.path)
        if found is None:
            raise PackFileError(FILE_MISSING.format(path=expected.path))
        if found.size != expected.size:
            raise PackFileError(FILE_WRONG_SIZE.format(path=expected.path))
        if found.sha256 != expected.sha256:
            raise PackFileError(FILE_ALTERED.format(path=expected.path))
    if len(by_path) != len(pack.files):  # a listed file the offered version does not have
        raise PackFileError(VERSION_NOT_OFFERED.format(version=document.version))
