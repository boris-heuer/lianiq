"""Synthetic languages and spy adapters for language pair contract tests (e2e data D-07).

``qaa`` and ``qab`` are BCP 47 private-use tags, so no real language is implied. The spy
adapters follow the ID-based adapter protocols of contract.md §3.1.6 and record every
construction, warm-up and call in memory.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from lianiq.languages import (
    Availability,
    CapabilityCatalog,
    DirectedEdge,
    LanguageDefinition,
    LanguageId,
    LanguageRegistry,
    ReadinessProbe,
)

QAA = LanguageId("qaa")
QAB = LanguageId("qab")

SYNTHETIC_LANGUAGES: tuple[LanguageDefinition, ...] = (
    LanguageDefinition(
        QAA,
        "Synthetic A",
        "Synthetic A (native)",
        {"whisper": "xa", "piper": "xa_XA"},
        Availability.QUALIFIED,
    ),
    LanguageDefinition(
        QAB,
        "Synthetic B",
        "Synthetic B (native)",
        {"whisper": "xb", "piper": "xb_XB"},
        Availability.QUALIFIED,
    ),
)


def synthetic_registry() -> LanguageRegistry:
    return LanguageRegistry(SYNTHETIC_LANGUAGES)


def write_model_directory(root: Path, relative: str, files: Mapping[str, bytes]) -> Path:
    directory = root / relative
    directory.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (directory / name).write_bytes(content)
    return directory


def write_model_file(root: Path, relative: str, content: bytes = b"voice") -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def manifest_record(root: Path, path: Path, **extra: object) -> dict[str, object]:
    """A manifest record in the shape ``scripts/download_models.py`` writes."""
    return {
        "path": path.relative_to(root).as_posix(),
        "repo_id": "synthetic/test",
        "revision": "0" * 40,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        **extra,
    }


def write_manifest(root: Path, records: Iterable[Mapping[str, object]], **extra: object) -> Path:
    path = root / "models" / "model-manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema_version": 1, "artifacts": list(records), **extra}
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def provisioned_catalog(
    root: Path,
    registry: LanguageRegistry,
    *,
    recognition: Iterable[str] = (),
    edges: Iterable[str] = (),
    voices: Iterable[str] = (),
) -> CapabilityCatalog:
    """A catalog whose listed capabilities are configured and present on disk (installed)."""
    stt = write_model_directory(root, "models/stt", {"model.bin": b"stt"})
    translation: dict[DirectedEdge, Path] = {}
    for key in edges:
        edge = DirectedEdge.from_key(key)
        translation[edge] = write_model_directory(
            root, f"models/mt-{edge.source}-{edge.target}", {"model.bin": key.encode()}
        )
    voice_paths = {
        language: write_model_file(root, f"models/voices/{language}.onnx") for language in voices
    }
    return CapabilityCatalog(
        registry,
        ReadinessProbe(root),
        recognition={language: stt for language in recognition},
        translation=translation,
        voices=voice_paths,
    )


@dataclass(frozen=True, slots=True)
class SyntheticTranscript:
    text: str
    language: str
    probability: float
    duration_seconds: float


@dataclass
class SpyRecognizer:
    """Returns scripted transcripts and records every ``transcribe`` call."""

    results: list[SyntheticTranscript] = field(default_factory=list)
    calls: list[str | None] = field(default_factory=list)
    warmed_up: bool = False

    def warm_up(self) -> None:
        self.warmed_up = True

    def transcribe(self, samples, sample_rate: int, language: str | None = None):
        self.calls.append(language)
        return self.results.pop(0)


@dataclass
class SpyTranslator:
    """Translates by tagging the text with the edge key and records every call."""

    calls: list[tuple[str, str, tuple[str, ...]]] = field(default_factory=list)
    warmed_edges: list[str] = field(default_factory=list)

    def warm_up(self, edges: Iterable[DirectedEdge]) -> None:
        self.warmed_edges.extend(edge.key for edge in edges)

    def translate(self, text: str, edge: DirectedEdge, context: tuple[str, ...] = ()) -> str:
        self.calls.append((text, edge.key, tuple(context)))
        return f"[{edge.key}] {text}"


@dataclass
class SpySynthesizer:
    """Records every ``synthesize`` call and returns a fake WAV path."""

    calls: list[tuple[str, str]] = field(default_factory=list)
    warmed_languages: list[str] = field(default_factory=list)

    def warm_up(self, languages: Iterable[str]) -> None:
        self.warmed_languages.extend(languages)

    def synthesize(self, text: str, language: str) -> Path:
        self.calls.append((text, language))
        return Path(f"synthetic-{language}.wav")
