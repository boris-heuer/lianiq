"""The model manifest, schema 1 with additive pack fields (CAP-0171 contract.md §3). Qt-free.

``models/model-manifest.json`` keeps ``schema_version`` 1 (CAP-0169 T2). Artifact records
gain ``pack_id`` and ``size``; a top-level ``packs[]`` holds one record per installed pack.
Unknown fields of the file and of artifact records are kept as they are.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal
from urllib.parse import urlsplit

from lianiq.packs.catalog import PackDefinition
from lianiq.packs.errors import ManifestError
from lianiq.packs.pack_file import PACK_FILE_NAME, render_pack_file

SCHEMA_VERSION = 1
PACK_SOURCES = frozenset({"download", "import", "script"})
PACK_FILE_REPO_ID = "lianiq"  # the pack file is written by Lianiq, not taken upstream


@dataclass(frozen=True, slots=True)
class PackRecord:
    id: str
    version: str
    source: Literal["download", "import", "script"]
    installed_at: datetime
    licence: str
    licence_accepted_at: datetime | None  # None for "script"

    def __post_init__(self) -> None:
        if self.source not in PACK_SOURCES:
            raise ValueError(f"Unknown pack source: {self.source!r}")

    def to_json(self) -> dict[str, Any]:
        accepted = self.licence_accepted_at
        return {
            "id": self.id,
            "version": self.version,
            "source": self.source,
            "installed_at": self.installed_at.isoformat(),
            "licence": self.licence,
            "licence_accepted_at": None if accepted is None else accepted.isoformat(),
        }

    @classmethod
    def from_json(cls, raw: object) -> PackRecord:
        try:
            if not isinstance(raw, dict):
                raise TypeError("not an object")
            accepted = raw["licence_accepted_at"]
            texts = [raw[key] for key in ("id", "version", "source", "installed_at", "licence")]
            if not all(isinstance(text, str) for text in texts):
                raise TypeError("not a string")
            return cls(
                id=raw["id"],
                version=raw["version"],
                source=raw["source"],
                installed_at=datetime.fromisoformat(raw["installed_at"]),
                licence=raw["licence"],
                licence_accepted_at=None if accepted is None else datetime.fromisoformat(accepted),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ManifestError(f"invalid packs[] record: {error.__class__.__name__}") from None


def repo_id(pack: PackDefinition) -> str:
    """Owner and name from the pack's source URL, e.g. ``Helsinki-NLP/opus-mt-de-zh``."""
    parts = [part for part in urlsplit(pack.source_url).path.split("/") if part]
    return "/".join(parts[:2]) if len(parts) >= 2 else pack.source_url


def _owned_paths(pack: PackDefinition) -> frozenset[str]:
    return frozenset(
        [f"{pack.root}/{item.path}" for item in pack.files] + [f"{pack.root}/{PACK_FILE_NAME}"]
    )


def _sort_key(item: Mapping[str, Any]) -> str:
    path = item.get("path")
    return path if isinstance(path, str) else ""


class Manifest:
    def __init__(
        self,
        artifacts: Iterable[Mapping[str, Any]] = (),
        packs: Iterable[PackRecord] = (),
        extra: Mapping[str, Any] | None = None,
    ) -> None:
        self._artifacts = tuple(
            MappingProxyType(dict(item)) for item in sorted(artifacts, key=_sort_key)
        )
        self._packs = tuple(sorted(packs, key=lambda record: record.id))
        self._extra = dict(extra or {})

    @property
    def artifacts(self) -> tuple[Mapping[str, Any], ...]:
        return self._artifacts

    @property
    def packs(self) -> tuple[PackRecord, ...]:
        return self._packs

    @classmethod
    def read(cls, path: Path) -> Manifest:
        """Missing file → empty manifest; unreadable or foreign content → ``ManifestError``."""
        path = Path(path)
        if not path.exists():
            return cls()
        try:
            payload: Any = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ManifestError(f"unreadable model manifest: {error.__class__.__name__}") from None
        if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
            raise ManifestError("unsupported model manifest schema_version")
        artifacts = payload.get("artifacts", [])
        packs = payload.get("packs", [])
        if not isinstance(artifacts, list) or not all(isinstance(i, dict) for i in artifacts):
            raise ManifestError("model manifest artifacts must be a list of objects")
        if not isinstance(packs, list):
            raise ManifestError("model manifest packs must be a list")
        records = [PackRecord.from_json(item) for item in packs]
        extra = {k: v for k, v in payload.items() if k not in ("artifacts", "packs")}
        return cls(artifacts, records, extra)

    def pack(self, pack_id: str) -> PackRecord | None:
        return next((record for record in self._packs if record.id == pack_id), None)

    def digests(self) -> Mapping[str, str]:
        """Recorded SHA-256 by repository-relative path."""
        return MappingProxyType(
            {
                item["path"]: item["sha256"].lower()
                for item in self._artifacts
                if isinstance(item.get("path"), str) and isinstance(item.get("sha256"), str)
            }
        )

    def with_pack(self, pack: PackDefinition, record: PackRecord) -> Manifest:
        """Replace the pack's artifact records and its ``packs[]`` record."""
        base = self.without_pack(pack)
        revision = pack.upstream_revision
        added: list[dict[str, Any]] = [
            {
                "path": f"{pack.root}/{item.path}",
                "repo_id": repo_id(pack),
                "revision": revision,
                "sha256": item.sha256,
                "pack_id": pack.id,
                "size": item.size,
            }
            for item in pack.files
        ]
        raw = render_pack_file(pack)
        added.append(
            {
                "path": f"{pack.root}/{PACK_FILE_NAME}",
                "repo_id": PACK_FILE_REPO_ID,
                "revision": pack.version,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "pack_id": pack.id,
                "size": len(raw),
            }
        )
        return Manifest([*base._artifacts, *added], [*base._packs, record], base._extra)

    def without_pack(self, pack: PackDefinition) -> Manifest:
        """Drop the ``packs[]`` record and every artifact record of a listed file or the pack."""
        owned = _owned_paths(pack)
        artifacts = [
            item
            for item in self._artifacts
            if item.get("pack_id") != pack.id and item.get("path") not in owned
        ]
        packs = [record for record in self._packs if record.id != pack.id]
        return Manifest(artifacts, packs, self._extra)

    def write(self, path: Path) -> None:
        """Write atomically: a temporary file in the same folder, then ``os.replace``."""
        path = Path(path)
        payload = {
            **self._extra,
            "schema_version": SCHEMA_VERSION,
            "artifacts": [dict(item) for item in self._artifacts],
            "packs": [record.to_json() for record in self._packs],
        }
        text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(text)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise
