"""Tiny synthetic packs for the CAP-0171 pack core tests (contract.md §1-§4).

The fixture packs use the repository default settings paths, so ``AppConfig()`` points at
them, but their files are a few bytes each. Nothing here touches the network.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from lianiq.config import AppConfig
from lianiq.languages import BUILTIN_REGISTRY, CapabilityCatalog, ReadinessProbe
from lianiq.packs.catalog import PackCatalog, PackDefinition
from lianiq.packs.manifest import Manifest, PackRecord
from lianiq.packs.pack_file import PACK_FILE_NAME, render_pack_file
from lianiq.packs.state import readiness_pack_files

MANIFEST = "models/model-manifest.json"
MT_ROOT = "models/opus-mt-de-zh"
VOICE_ROOT = "models/piper"
VOICE_FILE = "de_DE-thorsten-medium.onnx"
MT_FILES = {"pytorch_model.bin": b"weights de>zh-Hans", "config.json": b'{"d_model": 1}'}
VOICE_FILES = {VOICE_FILE: b"piper voice", f"{VOICE_FILE}.json": b'{"audio": 1}'}
WHEN = datetime(2026, 11, 19, 10, 15, 3, tzinfo=UTC)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_entry(path: str, data: bytes, *, url: bool = True) -> dict[str, Any]:
    return {
        "path": path,
        "size": len(data),
        "sha256": sha(data),
        "url": f"https://example.test/{path}" if url else None,
    }


def pack_entry(
    pack_id: str,
    kind: str,
    provides: list[str],
    root: str,
    files: Mapping[str, bytes],
    *,
    version: str = "1",
    archive: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": pack_id,
        "version": version,
        "kind": kind,
        "provides": provides,
        "root": root,
        "files": [file_entry(p, d, url=archive is None) for p, d in files.items()],
        "archive": archive,
        "publisher": "Example",
        "source_url": "https://example.test/example/model",
        "model": pack_id,
        "upstream_revision": "0" * 40,
        "licence": "MIT",
        "use_constraints": "",
    }


def mt_entry(version: str = "1", files: Mapping[str, bytes] = MT_FILES) -> dict[str, Any]:
    return pack_entry("mt-a", "translation", ["de>zh-Hans"], MT_ROOT, files, version=version)


def voice_entry() -> dict[str, Any]:
    return pack_entry("tts-a", "voice", ["de"], VOICE_ROOT, VOICE_FILES)


def write_catalog(path: Path, entries: list[dict[str, Any]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"format": "lianiq-catalog/v1", "packs": entries}), "utf-8")
    return path


def load_catalog(folder: Path, *entries: dict[str, Any], name: str = "catalog.json"):
    return PackCatalog.load(write_catalog(folder / name, list(entries)), BUILTIN_REGISTRY)


def fixture_packs(folder: Path) -> PackCatalog:
    return load_catalog(folder, mt_entry(), voice_entry())


def write_files(project: Path, root: str, files: Mapping[str, bytes]) -> None:
    for name, data in files.items():
        target = project / root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)


def record(pack: PackDefinition, source: str = "download") -> PackRecord:
    accepted = None if source == "script" else WHEN
    return PackRecord(pack.id, pack.version, source, WHEN, pack.licence, accepted)  # type: ignore[arg-type]


def install(project: Path, pack: PackDefinition, files: Mapping[str, bytes]) -> Manifest:
    """An app install: files, the pack's own ``lianiq-pack.json`` and a ``packs[]`` record."""
    write_files(project, pack.root, files)
    (project / pack.root / PACK_FILE_NAME).write_bytes(render_pack_file(pack))
    manifest = Manifest.read(project / MANIFEST).with_pack(pack, record(pack))
    manifest.write(project / MANIFEST)
    return manifest


def script_install(project: Path, pack: PackDefinition, files: Mapping[str, bytes]) -> Manifest:
    """An install by an older ``download_models.py``: artifacts only, no ``packs[]`` record."""
    write_files(project, pack.root, files)
    target = project / MANIFEST
    target.parent.mkdir(parents=True, exist_ok=True)
    artifacts = [
        {"path": f"{pack.root}/{n}", "repo_id": "x/y", "revision": "r", "sha256": sha(d)}
        for n, d in files.items()
    ]
    target.write_text(json.dumps({"schema_version": 1, "artifacts": artifacts}), "utf-8")
    return Manifest.read(target)


def capability_catalog(
    project: Path, packs: PackCatalog, manifest: Manifest, config: AppConfig | None = None
) -> CapabilityCatalog:
    config = config or AppConfig()
    pack_files = readiness_pack_files(packs, manifest, config, project)
    probe = ReadinessProbe(project, pack_files=pack_files)
    return CapabilityCatalog.from_config(config, BUILTIN_REGISTRY, probe)
