"""Directed language capabilities and their readiness (contract.md §3.1.2).

Recognition is a capability per language, translation per directed edge and voice per
language. A reverse edge is never derived from a configured edge. Readiness is read from
the filesystem and ``models/model-manifest.json`` schema 1 as written by
``scripts/download_models.py``; the manifest is never modified here.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from lianiq.languages.errors import SameLanguagePairError
from lianiq.languages.registry import LanguageId, LanguageRegistry, normalize_language_id

if TYPE_CHECKING:
    from lianiq.config import AppConfig

MANIFEST_SCHEMA_VERSION = 1
MANIFEST_RELATIVE_PATH = Path("models") / "model-manifest.json"
EDGE_SEPARATOR = ">"


class ReadinessStatus(str, Enum):
    NOT_CONFIGURED = "not_configured"  # no entry in settings
    MISSING = "missing"  # configured, required files absent
    INSTALLED = "installed"  # files present, no manifest record
    VALIDATED = "validated"  # files present, manifest sha256 matches
    INVALID = "invalid"  # manifest record does not match

    @property
    def is_ready(self) -> bool:
        return self in (ReadinessStatus.INSTALLED, ReadinessStatus.VALIDATED)


@dataclass(frozen=True, slots=True)
class DirectedEdge:
    source: LanguageId
    target: LanguageId

    def __post_init__(self) -> None:
        object.__setattr__(self, "source", normalize_language_id(self.source))
        object.__setattr__(self, "target", normalize_language_id(self.target))
        if self.source == self.target:
            raise SameLanguagePairError(self.source)

    @property
    def key(self) -> str:
        return f"{self.source}{EDGE_SEPARATOR}{self.target}"

    @classmethod
    def from_key(cls, key: str) -> DirectedEdge:
        source, separator, target = key.partition(EDGE_SEPARATOR)
        if not separator or not source or not target:
            raise ValueError(f"Invalid directed edge key: {key!r}")
        return cls(LanguageId(source), LanguageId(target))

    def reversed(self) -> DirectedEdge:
        return DirectedEdge(self.target, self.source)


@dataclass(frozen=True, slots=True)
class RecognitionCapability:
    language: LanguageId
    model_path: Path | None  # None only when NOT_CONFIGURED
    status: ReadinessStatus


@dataclass(frozen=True, slots=True)
class TranslationCapability:
    edge: DirectedEdge
    model_path: Path | None  # None only when NOT_CONFIGURED
    status: ReadinessStatus


@dataclass(frozen=True, slots=True)
class VoiceCapability:
    language: LanguageId
    voice_path: Path | None  # file or model directory; None only when NOT_CONFIGURED
    status: ReadinessStatus


class ReadinessProbe:
    """Read-only readiness of configured model files and directories.

    Paths in the manifest are repository-relative POSIX paths below ``root``. A capability's
    records are the artifacts whose path equals its configured file or lies under its
    configured directory. Digests are computed only when a capability is probed and are
    cached by (path, size, mtime).
    """

    def __init__(self, root: Path, manifest_path: Path | None = None) -> None:
        self.root = Path(root)
        self.manifest_path = (
            Path(manifest_path) if manifest_path is not None else self.root / MANIFEST_RELATIVE_PATH
        )
        self._records: dict[str, str] | None = None
        self._manifest_problem: str | None = None
        self._digests: dict[tuple[str, int, int], str] = {}

    @property
    def manifest_problem(self) -> str | None:
        """Why the manifest could not be used (reported by ``doctor.py``), or ``None``."""
        self._load_manifest()
        return self._manifest_problem

    def resolve(self, value: str | Path) -> Path:
        path = Path(value).expanduser()
        return path if path.is_absolute() else self.root / path

    def probe_file(self, path: Path) -> ReadinessStatus:
        if not path.is_file():
            return ReadinessStatus.MISSING
        relative = self._relative(path)
        records = self._load_manifest()
        if relative is None or relative not in records:
            return ReadinessStatus.INSTALLED
        return self._status_of({relative: records[relative]})

    def probe_directory(self, path: Path) -> ReadinessStatus:
        if not path.is_dir():
            return ReadinessStatus.MISSING
        relative = self._relative(path)
        records = self._load_manifest()
        if relative is None:
            return ReadinessStatus.INSTALLED
        prefix = f"{relative}/"
        owned = {
            record_path: digest
            for record_path, digest in records.items()
            if record_path.startswith(prefix)
        }
        if not owned:
            return ReadinessStatus.INSTALLED
        return self._status_of(owned)

    def _status_of(self, records: Mapping[str, str]) -> ReadinessStatus:
        for record_path, expected in records.items():
            file_path = self.root / Path(record_path)
            if not file_path.is_file() or self._digest(file_path) != expected.lower():
                return ReadinessStatus.INVALID
        return ReadinessStatus.VALIDATED

    def _relative(self, path: Path) -> str | None:
        try:
            return path.resolve().relative_to(self.root.resolve()).as_posix()
        except ValueError:
            return None

    def _digest(self, path: Path) -> str:
        stat = path.stat()
        cache_key = (str(path.resolve()), stat.st_size, stat.st_mtime_ns)
        cached = self._digests.get(cache_key)
        if cached is None:
            cached = self._hash_file(path)
            self._digests[cache_key] = cached
        return cached

    @staticmethod
    def _hash_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    def _load_manifest(self) -> dict[str, str]:
        if self._records is not None:
            return self._records
        self._records = {}
        if not self.manifest_path.exists():
            return self._records
        try:
            payload: Any = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            self._manifest_problem = f"unreadable model manifest: {error.__class__.__name__}"
            return self._records
        if not isinstance(payload, dict) or payload.get("schema_version") != (
            MANIFEST_SCHEMA_VERSION
        ):
            version = payload.get("schema_version") if isinstance(payload, dict) else None
            self._manifest_problem = f"unsupported model manifest schema_version: {version!r}"
            return self._records
        artifacts = payload.get("artifacts")
        for item in artifacts if isinstance(artifacts, list) else ():
            if not isinstance(item, dict):
                continue
            record_path = item.get("path")
            digest = item.get("sha256")
            if isinstance(record_path, str) and isinstance(digest, str):
                self._records[record_path] = digest
        return self._records


class CapabilityCatalog:
    """Configured recognition languages, directed translation edges and voices.

    Readiness is probed only when a capability is looked up, so only the capabilities a
    mode requires are hashed; digests are cached by the probe.
    """

    def __init__(
        self,
        registry: LanguageRegistry,
        probe: ReadinessProbe,
        *,
        recognition: Mapping[str, Path] | None = None,
        translation: Mapping[DirectedEdge, Path] | None = None,
        voices: Mapping[str, Path] | None = None,
    ) -> None:
        self.registry = registry
        self._probe = probe
        self._recognition = {
            registry.get(language).id: probe.resolve(path)
            for language, path in (recognition or {}).items()
        }
        self._translation: dict[DirectedEdge, Path] = {}
        for edge, path in (translation or {}).items():
            registry.get(edge.source)
            registry.get(edge.target)
            self._translation[edge] = probe.resolve(path)
        self._voices = {
            registry.get(language).id: probe.resolve(path)
            for language, path in (voices or {}).items()
        }

    @classmethod
    def from_config(
        cls, config: AppConfig, registry: LanguageRegistry, probe: ReadinessProbe
    ) -> CapabilityCatalog:
        """Build the catalog from settings schema v2 (contract.md §4.2).

        Recognition languages come from ``speech_to_text.languages`` (one shared model),
        directed edges from ``translation.edges`` keyed ``"<source>><target>"`` and voices
        from ``tts.voices`` keyed by language ID. An empty path counts as not configured.
        """
        model_path = config.speech_to_text.model_path
        recognition = (
            {language: Path(model_path) for language in config.speech_to_text.languages}
            if model_path
            else {}
        )
        translation = {
            DirectedEdge.from_key(key): Path(edge.model_path)
            for key, edge in config.translation.edges.items()
            if edge.model_path
        }
        voices = {language: Path(path) for language, path in config.tts.voices.items() if path}
        return cls(registry, probe, recognition=recognition, translation=translation, voices=voices)

    # Configured paths without probing readiness; adapters are built from these.
    def translation_paths(self) -> Mapping[DirectedEdge, Path]:
        """Every configured directed edge and its resolved model directory."""
        return MappingProxyType(dict(self._translation))

    def voice_paths(self) -> Mapping[LanguageId, Path]:
        """Every configured voice by language ID and its resolved voice file or directory."""
        return MappingProxyType(dict(self._voices))

    def recognition(self, language: LanguageId) -> RecognitionCapability:
        language_id = self.registry.get(language).id
        path = self._recognition.get(language_id)
        status = (
            ReadinessStatus.NOT_CONFIGURED if path is None else self._probe.probe_directory(path)
        )
        return RecognitionCapability(language_id, path, status)

    def translation(self, edge: DirectedEdge) -> TranslationCapability:
        """Readiness of exactly ``edge``; the reverse edge is never consulted."""
        self.registry.get(edge.source)
        self.registry.get(edge.target)
        path = self._translation.get(edge)
        status = (
            ReadinessStatus.NOT_CONFIGURED if path is None else self._probe.probe_directory(path)
        )
        return TranslationCapability(edge, path, status)

    def voice(self, language: LanguageId) -> VoiceCapability:
        language_id = self.registry.get(language).id
        path = self._voices.get(language_id)
        if path is None:
            status = ReadinessStatus.NOT_CONFIGURED
        elif path.is_dir():  # a voice model directory (sherpa-onnx)
            status = self._probe.probe_directory(path)
        else:  # a voice file (Piper)
            status = self._probe.probe_file(path)
        return VoiceCapability(language_id, path, status)
