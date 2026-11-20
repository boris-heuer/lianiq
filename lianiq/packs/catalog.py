"""The built-in language-pack catalog and its load rules (CAP-0171 contract.md §1). Qt-free.

Packs name languages only by registry id: recognition and voice packs provide language ids,
translation packs directed edge keys. A pack never comes from the network; new versions
arrive with a new Lianiq release.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from lianiq.languages.capabilities import DirectedEdge
from lianiq.languages.errors import LanguageContractError
from lianiq.languages.registry import Availability, LanguageRegistry
from lianiq.languages.requirements import Requirement, RequirementKind
from lianiq.packs.errors import PackCatalogError, UnknownPackError
from lianiq.packs.paths import is_safe_relative  # re-exported for pack_file and callers

BUILTIN_CATALOG_PATH = Path(__file__).resolve().with_name("builtin_catalog.json")
CATALOG_FORMAT = "lianiq-catalog/v1"
MODELS_PREFIX = "models/"
RESERVED_FILE_NAME = "lianiq-pack.json"  # pack_file.PACK_FILE_NAME; never a listed file
_HEX64 = re.compile(r"[0-9a-f]{64}")
_PACK_KEYS = frozenset(
    {
        "id",
        "version",
        "kind",
        "provides",
        "root",
        "files",
        "archive",
        "publisher",
        "source_url",
        "model",
        "upstream_revision",
        "licence",
        "use_constraints",
    }
)
_FILE_KEYS = frozenset({"path", "size", "sha256", "url"})
_ARCHIVE_KEYS = frozenset({"url", "size", "sha256", "top_level"})


class PackKind(StrEnum):
    RECOGNITION = "recognition"
    TRANSLATION = "translation"
    VOICE = "voice"


_REQUIREMENT_KINDS = {
    RequirementKind.RECOGNITION: PackKind.RECOGNITION,
    RequirementKind.TRANSLATION: PackKind.TRANSLATION,
    RequirementKind.VOICE: PackKind.VOICE,
}


@dataclass(frozen=True, slots=True)
class PackFile:
    path: str  # POSIX, relative to the pack root; no "..", drive or leading "/"
    size: int  # exact bytes
    sha256: str  # 64 lowercase hex
    url: str | None  # pinned HTTPS URL; None for files taken from an archive


@dataclass(frozen=True, slots=True)
class PackArchive:
    url: str
    size: int
    sha256: str
    top_level: str


@dataclass(frozen=True, slots=True)
class PackDefinition:
    id: str
    version: str
    kind: PackKind
    provides: tuple[str, ...]  # language ids (recognition, voice) or edge keys
    root: str  # repository-relative POSIX below models/
    files: tuple[PackFile, ...]
    archive: PackArchive | None
    publisher: str
    source_url: str
    model: str
    upstream_revision: str
    licence: str
    use_constraints: str

    @property
    def installed_bytes(self) -> int:
        return sum(item.size for item in self.files)

    @property
    def download_bytes(self) -> int:
        return self.archive.size if self.archive is not None else self.installed_bytes


def is_sha256(value: object) -> bool:
    return isinstance(value, str) and _HEX64.fullmatch(value) is not None


def is_size(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _text(raw: dict[str, Any], key: str, where: str, *, empty: bool = False) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or (not value and not empty):
        raise PackCatalogError(f"{where}: {key} must be a {'' if empty else 'non-empty '}string")
    return value


def _https(value: object, where: str) -> str:
    if not isinstance(value, str) or not value.startswith("https://"):
        raise PackCatalogError(f"{where}: URL must be HTTPS")
    return value


def _keys(raw: object, allowed: frozenset[str], where: str) -> dict[str, Any]:
    if not isinstance(raw, dict) or set(raw) != allowed:
        raise PackCatalogError(f"{where}: fields must be exactly {', '.join(sorted(allowed))}")
    return raw


def _file(raw: object, where: str, archived: bool) -> PackFile:
    item = _keys(raw, _FILE_KEYS, where)
    path = item["path"]
    if not is_safe_relative(path) or path == RESERVED_FILE_NAME:
        raise PackCatalogError(f"{where}: unsafe path {path!r}")
    if not is_size(item["size"]) or not is_sha256(item["sha256"]):
        raise PackCatalogError(f"{where}: {path}: size or sha256 is invalid")
    if archived and item["url"] is not None:
        raise PackCatalogError(f"{where}: {path}: a file of an archive has no URL")
    url = None if archived else _https(item["url"], f"{where}: {path}")
    return PackFile(path, item["size"], item["sha256"], url)


def _archive(raw: object, where: str) -> PackArchive | None:
    if raw is None:
        return None
    item = _keys(raw, _ARCHIVE_KEYS, f"{where} archive")
    if not is_size(item["size"]) or not is_sha256(item["sha256"]):
        raise PackCatalogError(f"{where}: archive size or sha256 is invalid")
    if not is_safe_relative(item["top_level"]):
        raise PackCatalogError(f"{where}: archive top_level is unsafe")
    return PackArchive(_https(item["url"], where), item["size"], item["sha256"], item["top_level"])


def _subject(kind: PackKind, value: object, registry: LanguageRegistry, where: str) -> str:
    if not isinstance(value, str):
        raise PackCatalogError(f"{where}: provides must hold strings")
    try:
        if kind is PackKind.TRANSLATION:
            edge = DirectedEdge.from_key(value)
            languages, canonical = [edge.source, edge.target], edge.key
        else:
            languages = [registry.get(value).id]
            canonical = languages[0]
        for language in languages:
            if registry.get(language).availability is not Availability.QUALIFIED:
                raise PackCatalogError(f"{where}: {language} is not a qualified language")
    except (LanguageContractError, ValueError) as error:
        raise PackCatalogError(f"{where}: {value!r} is not a registry capability") from error
    if canonical != value:
        raise PackCatalogError(f"{where}: {value!r} must be written as {canonical!r}")
    return value


def _pack(raw: object, registry: LanguageRegistry, index: int) -> PackDefinition:
    item = _keys(raw, _PACK_KEYS, f"pack {index}")
    where = f"pack {item['id']!r}" if isinstance(item["id"], str) else f"pack {index}"
    try:
        kind = PackKind(item["kind"])
    except ValueError:
        raise PackCatalogError(f"{where}: unknown kind {item['kind']!r}") from None
    provides = item["provides"]
    if not isinstance(provides, list) or not provides:
        raise PackCatalogError(f"{where}: provides must be a non-empty list")
    root = _text(item, "root", where)
    if not root.startswith(MODELS_PREFIX) or not is_safe_relative(root):
        raise PackCatalogError(f"{where}: root must lie under {MODELS_PREFIX}")
    archive = _archive(item["archive"], where)
    files = item["files"]
    if not isinstance(files, list) or not files:
        raise PackCatalogError(f"{where}: files must be a non-empty list")
    listed = tuple(_file(entry, where, archive is not None) for entry in files)
    if len({entry.path for entry in listed}) != len(listed):
        raise PackCatalogError(f"{where}: a file is listed twice")
    return PackDefinition(
        id=_text(item, "id", where),
        version=_text(item, "version", where),
        kind=kind,
        provides=tuple(_subject(kind, value, registry, where) for value in provides),
        root=root,
        files=listed,
        archive=archive,
        publisher=_text(item, "publisher", where),
        source_url=_https(item["source_url"], where),
        model=_text(item, "model", where),
        upstream_revision=_text(item, "upstream_revision", where),
        licence=_text(item, "licence", where),
        use_constraints=_text(item, "use_constraints", where, empty=True),
    )


class PackCatalog:
    def __init__(self, packs: tuple[PackDefinition, ...]) -> None:
        self._packs = packs
        self._by_id: dict[str, PackDefinition] = {}
        self._by_capability: dict[tuple[PackKind, str], PackDefinition] = {}
        roots: set[str] = set()
        for pack in packs:
            if pack.id in self._by_id:
                raise PackCatalogError(f"pack {pack.id!r} is listed twice")
            if pack.root in roots:
                raise PackCatalogError(f"pack {pack.id!r}: root {pack.root} is not unique")
            for subject in pack.provides:
                if (pack.kind, subject) in self._by_capability:
                    raise PackCatalogError(f"pack {pack.id!r}: {subject} is already provided")
                self._by_capability[(pack.kind, subject)] = pack
            self._by_id[pack.id] = pack
            roots.add(pack.root)

    @classmethod
    def load(cls, path: Path, registry: LanguageRegistry) -> PackCatalog:
        """Read and check a catalog file; any violation raises ``PackCatalogError``."""
        try:
            payload: Any = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise PackCatalogError(f"unreadable catalog: {error.__class__.__name__}") from None
        if not isinstance(payload, dict) or payload.get("format") != CATALOG_FORMAT:
            raise PackCatalogError(f"catalog format must be {CATALOG_FORMAT}")
        packs = payload.get("packs")
        if not isinstance(packs, list):
            raise PackCatalogError("catalog packs must be a list")
        return cls(tuple(_pack(raw, registry, index) for index, raw in enumerate(packs)))

    def packs(self) -> tuple[PackDefinition, ...]:
        return self._packs

    def get(self, pack_id: str) -> PackDefinition:
        try:
            return self._by_id[pack_id]
        except KeyError:
            raise UnknownPackError(pack_id) from None

    def for_requirement(self, requirement: Requirement) -> PackDefinition | None:
        """The pack that provides a capability requirement; ``None`` for devices."""
        kind = _REQUIREMENT_KINDS.get(requirement.kind)
        if kind is None or requirement.subject is None:
            return None
        return self._by_capability.get((kind, requirement.subject))
