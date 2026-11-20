"""Pack states and language rows (CAP-0171 contract.md §4). Qt-free.

``pack_status`` judges every listed file of a pack: those of its installed
``lianiq-pack.json`` when a ``packs[]`` record exists, so an older installed version is
judged against its own list, otherwise those of the catalog entry. Digests come from the
probe's ``PackVerifier``; call it from a worker thread, never at launch.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

from lianiq.languages.capabilities import CapabilityCatalog, DirectedEdge, ReadinessStatus
from lianiq.languages.pack_readiness import normalize_key
from lianiq.languages.registry import Availability, LanguageId, LanguageRegistry
from lianiq.packs.catalog import PackCatalog, PackDefinition, PackFile, PackKind
from lianiq.packs.errors import PackFileError
from lianiq.packs.jobs import JobView
from lianiq.packs.manifest import Manifest
from lianiq.packs.pack_file import PACK_FILE_NAME, parse_pack_file

if TYPE_CHECKING:
    from lianiq.config import AppConfig

FILES_MISSING = "{count} files missing"
FILE_MISSING = "1 file missing"
INTEGRITY_FAILED = "integrity check failed"
PACK_FILE_MISSING = "pack file missing"
PACK_FILE_INVALID = "pack file invalid"


class PackState(StrEnum):
    PLANNED = "planned"
    UNSUPPORTED = "unsupported"
    DOWNLOADABLE = "downloadable"
    INSTALLING = "installing"
    INSTALLED = "installed"
    VALIDATED = "validated"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class PackStatus:
    state: PackState
    reason: str | None  # e.g. "2 files missing", "integrity check failed", last job error
    update_available: bool  # a packs[] record of another version than the catalog's
    custom_path: bool  # settings point a provided capability outside the pack root


@dataclass(frozen=True, slots=True)
class LanguageRow:
    subject: LanguageId | DirectedEdge  # a language (recognition, voice) or a directed edge
    kind: PackKind
    state: PackState  # PLANNED, UNSUPPORTED, or DOWNLOADABLE for a row with a catalog pack
    pack_id: str | None  # None for planned or unsupported rows


def installed_files(
    pack: PackDefinition, manifest: Manifest, project_root: Path
) -> tuple[tuple[PackFile, ...], str | None]:
    """The listed files of ``pack`` and, for an unusable installed pack file, the reason."""
    record = manifest.pack(pack.id)
    if record is None:
        return pack.files, None
    try:
        raw = (project_root / pack.root / PACK_FILE_NAME).read_bytes()
    except OSError:
        return pack.files, PACK_FILE_MISSING
    try:
        document = parse_pack_file(raw)
    except PackFileError:
        return pack.files, PACK_FILE_INVALID
    if document.id != pack.id or document.version != record.version:
        return pack.files, PACK_FILE_INVALID
    return document.files, None


def _pack_file_entry(pack: PackDefinition, manifest: Manifest) -> tuple[PackFile, ...]:
    """The recorded ``lianiq-pack.json`` of an installed pack as a listed file, if any."""
    if manifest.pack(pack.id) is None:
        return ()
    path = f"{pack.root}/{PACK_FILE_NAME}"
    for item in manifest.artifacts:
        size, digest = item.get("size"), item.get("sha256")
        if item.get("path") == path and isinstance(size, int) and isinstance(digest, str):
            return (PackFile(PACK_FILE_NAME, size, digest.lower(), None),)
    return ()


def _configured(config: AppConfig, kind: PackKind, subject: str) -> str:
    if kind is PackKind.RECOGNITION:
        stt = config.speech_to_text
        return stt.model_path if subject in stt.languages else ""
    if kind is PackKind.TRANSLATION:
        edge = config.translation.edges.get(subject)
        return edge.model_path if edge is not None else ""
    return config.tts.voices.get(subject, "")


def _relative_key(project_root: Path, value: str) -> str | None:
    path = Path(value).expanduser()
    path = path if path.is_absolute() else project_root / path
    try:
        return normalize_key(path.resolve().relative_to(project_root.resolve()).as_posix())
    except ValueError:
        return None


def _default_paths(pack: PackDefinition, files: tuple[PackFile, ...]) -> set[str]:
    return {pack.root} | {f"{pack.root}/{item.path}" for item in (*pack.files, *files)}


def readiness_pack_files(
    packs: PackCatalog, manifest: Manifest, config: AppConfig, project_root: Path
) -> dict[str, tuple[PackFile, ...]]:
    """``ReadinessProbe(pack_files=...)`` for every provided capability at a default path.

    Keys are the configured capability paths that equal a pack root or a listed file;
    values hold the listed files (and the recorded pack file) relative to the project root.
    """
    result: dict[str, tuple[PackFile, ...]] = {}
    for pack in packs.packs():
        files, _ = installed_files(pack, manifest, project_root)
        defaults = _default_paths(pack, files)
        entries = tuple(
            PackFile(f"{pack.root}/{item.path}", item.size, item.sha256, None)
            for item in (*files, *_pack_file_entry(pack, manifest))
        )
        for subject in pack.provides:
            value = _configured(config, pack.kind, subject)
            key = _relative_key(project_root, value) if value else None
            if key is not None and key in defaults:
                result[key] = entries
    return result


def _capability(catalog: CapabilityCatalog, kind: PackKind, subject: str) -> ReadinessStatus:
    if kind is PackKind.RECOGNITION:
        return catalog.recognition(LanguageId(subject)).status
    if kind is PackKind.TRANSLATION:
        return catalog.translation(DirectedEdge.from_key(subject)).status
    return catalog.voice(LanguageId(subject)).status


def _missing(count: int) -> str:
    return FILE_MISSING if count == 1 else FILES_MISSING.format(count=count)


def pack_status(
    pack: PackDefinition,
    catalog: CapabilityCatalog,
    manifest: Manifest,
    config: AppConfig,
    job: JobView | None,
    last_error: str | None,
) -> PackStatus:
    """The state of one catalog pack; the first matching rule of contract.md §4 wins."""
    probe = catalog.probe
    record = manifest.pack(pack.id)
    files, problem = installed_files(pack, manifest, probe.root)
    defaults = _default_paths(pack, files)
    custom = False
    for subject in pack.provides:
        value = _configured(config, pack.kind, subject)
        custom = custom or bool(value) and _relative_key(probe.root, value) not in defaults
    update = record is not None and record.version != pack.version

    def status(state: PackState, reason: str | None = None) -> PackStatus:
        return PackStatus(state, reason, update, custom)

    if job is not None and job.pack_id == pack.id:
        return status(PackState.INSTALLING)
    if last_error:
        return status(PackState.FAILED, last_error)
    if problem is not None:
        return status(PackState.FAILED, problem)
    base = probe.root / pack.root
    if record is not None:
        digests = manifest.digests()
        expected = {
            item.path: digests[f"{pack.root}/{item.path}"]
            for item in files
            if f"{pack.root}/{item.path}" in digests
        }
        listed = (*files, *_pack_file_entry(pack, manifest))
        report = probe.verifier.inspect(base, listed, expected)
        if report.missing:
            return status(PackState.FAILED, _missing(len(report.missing)))
        if not report.ok:
            return status(PackState.FAILED, INTEGRITY_FAILED)
    capabilities = [_capability(catalog, pack.kind, subject) for subject in pack.provides]
    if ReadinessStatus.INVALID in capabilities:
        return status(PackState.FAILED, INTEGRITY_FAILED)
    if record is not None and all(s is ReadinessStatus.VALIDATED for s in capabilities):
        return status(PackState.VALIDATED)
    present = probe.verifier.inspect(base, files, digests=False).ok
    if present and all(s.is_ready for s in capabilities):
        return status(PackState.INSTALLED)
    return status(PackState.DOWNLOADABLE)


def language_rows(registry: LanguageRegistry, packs: PackCatalog) -> tuple[LanguageRow, ...]:
    """Recognition rows, then directed translation edges, then voice rows, in registry order.

    A planned language (or an edge with one) is ``planned``; a qualified capability without
    a catalog pack is ``unsupported``; a row with a pack carries its id and the catalog
    baseline ``downloadable`` (the page shows ``pack_status`` for it).
    """
    languages = registry.languages()
    edges = [DirectedEdge(a.id, b.id) for a in languages for b in languages if a.id != b.id]
    qualified = {d.id for d in languages if d.availability is Availability.QUALIFIED}
    by_capability = {
        (pack.kind, subject): pack.id for pack in packs.packs() for subject in pack.provides
    }

    def row(kind: PackKind, subject: LanguageId | DirectedEdge) -> LanguageRow:
        members = (
            (subject.source, subject.target) if isinstance(subject, DirectedEdge) else (subject,)
        )
        if not all(member in qualified for member in members):
            return LanguageRow(subject, kind, PackState.PLANNED, None)
        key = subject.key if isinstance(subject, DirectedEdge) else subject
        pack_id = by_capability.get((kind, key))
        if pack_id is None:
            return LanguageRow(subject, kind, PackState.UNSUPPORTED, None)
        return LanguageRow(subject, kind, PackState.DOWNLOADABLE, pack_id)

    return (
        *(row(PackKind.RECOGNITION, d.id) for d in languages),
        *(row(PackKind.TRANSLATION, edge) for edge in edges),
        *(row(PackKind.VOICE, d.id) for d in languages),
    )
