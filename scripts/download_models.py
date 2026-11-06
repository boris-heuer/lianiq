from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tarfile
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from huggingface_hub import hf_hub_download, snapshot_download

ROOT = Path(__file__).resolve().parent.parent
MODELS = ROOT / "models"
MANIFEST = MODELS / "model-manifest.json"


@dataclass(frozen=True)
class SnapshotSpec:
    repo_id: str
    revision: str
    destination: Path
    allow_patterns: list[str] | None = None


@dataclass(frozen=True)
class PiperFileSpec:
    filename: str
    destination: Path


@dataclass(frozen=True)
class ArchiveSpec:
    """A pinned release archive: exact size and SHA-256, and the files taken from it."""

    url: str
    size: int
    sha256: str
    top_level: str
    files: tuple[str, ...]
    destination: Path
    repo_id: str


# Commit IDs make every network fetch resolve to the reviewed repository state.
FASTER_WHISPER = SnapshotSpec(
    "Systran/faster-whisper-small",
    "536b0662742c02347bc0e980a01041f333bce120",
    MODELS / "faster-whisper-small",
)
MARIAN_SNAPSHOTS = (
    SnapshotSpec(
        "Helsinki-NLP/opus-mt-de-zh",
        "cf77098253bb466b05d2beafd3a3c3dea92ed23b",
        MODELS / "opus-mt-de-zh",
        ["*.json", "*.spm", "pytorch_model.bin", "README.md"],
    ),
    SnapshotSpec(
        "Helsinki-NLP/opus-mt-zh-de",
        "799162f10e25405aaa5088ca013295596a4ca517",
        MODELS / "opus-mt-zh-de",
        ["*.json", "*.spm", "pytorch_model.bin", "README.md"],
    ),
)
PIPER_VOICES_REVISION = "c10ece1aade47bb51c153c893d14e5bf8e5b7117"
PIPER_VOICE_FILES = (
    PiperFileSpec(
        "de/de_DE/thorsten/medium/de_DE-thorsten-medium.onnx",
        MODELS / "piper" / "de_DE-thorsten-medium.onnx",
    ),
    PiperFileSpec(
        "de/de_DE/thorsten/medium/de_DE-thorsten-medium.onnx.json",
        MODELS / "piper" / "de_DE-thorsten-medium.onnx.json",
    ),
    PiperFileSpec(
        "de/de_DE/thorsten/medium/MODEL_CARD",
        MODELS / "piper" / "de_DE-thorsten-medium.MODEL_CARD.md",
    ),
)

# The archive is untrusted data until its size and SHA-256 match; only the listed regular
# files directly below ``top_level`` are extracted, under names taken from this list.
SHERPA_MANDARIN_VOICE = ArchiveSpec(
    url=(
        "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/"
        "vits-icefall-zh-aishell3.tar.bz2"
    ),
    size=31_559_701,
    sha256="ab468db3a3308cdd861495e0db2f25d79418a0c00639f74944c7cdf5dd8c6ec1",
    top_level="vits-icefall-zh-aishell3",
    files=(
        "model.onnx",
        "lexicon.txt",
        "tokens.txt",
        "phone.fst",
        "date.fst",
        "number.fst",
        "new_heteronym.fst",
        "rule.far",
        "speakers.txt",
    ),
    destination=MODELS / "sherpa" / "vits-icefall-zh-aishell3",
    repo_id="k2-fsa/sherpa-onnx",
)
MAX_EXTRACTED_FILE_BYTES = 512 * 1024 * 1024


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def manifest_entry(path: Path, repo_id: str, revision: str) -> dict[str, str]:
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "repo_id": repo_id,
        "revision": revision,
        "sha256": sha256_file(path),
    }


def download_snapshot(spec: SnapshotSpec) -> list[dict[str, str]]:
    print(f"Downloading {spec.repo_id}@{spec.revision} -> {spec.destination}")
    spec.destination.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        repo_id=spec.repo_id,
        revision=spec.revision,
        local_dir=spec.destination,
        allow_patterns=spec.allow_patterns,
    )
    return [
        manifest_entry(path, spec.repo_id, spec.revision)
        for path in sorted(spec.destination.rglob("*"))
        if path.is_file() and ".cache" not in path.parts
    ]


def download_piper_file(spec: PiperFileSpec) -> dict[str, str]:
    repo_id = "rhasspy/piper-voices"
    print(f"Downloading {repo_id}@{PIPER_VOICES_REVISION}/{spec.filename}")
    cached = Path(
        hf_hub_download(
            repo_id=repo_id,
            filename=spec.filename,
            revision=PIPER_VOICES_REVISION,
        )
    )
    spec.destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(cached, spec.destination)
    return manifest_entry(spec.destination, repo_id, PIPER_VOICES_REVISION)


def fetch_archive(spec: ArchiveSpec, target: Path) -> None:
    """Stream ``spec.url`` to ``target``; fail on any size or SHA-256 difference."""
    digest = hashlib.sha256()
    received = 0
    with urllib.request.urlopen(spec.url, timeout=60) as response, target.open("wb") as out:
        for block in iter(lambda: response.read(1024 * 1024), b""):
            received += len(block)
            if received > spec.size:
                raise ValueError(f"{spec.url} is larger than the pinned {spec.size} bytes")
            digest.update(block)
            out.write(block)
    if received != spec.size:
        raise ValueError(f"{spec.url} has {received} bytes, expected {spec.size}")
    if digest.hexdigest() != spec.sha256:
        raise ValueError(f"{spec.url} SHA-256 {digest.hexdigest()} does not match the pin")


def extract_archive(spec: ArchiveSpec, archive: Path, staging: Path) -> None:
    """Extract only the pinned regular files of ``spec`` into ``staging`` (no paths, links)."""
    if sha256_file(archive) != spec.sha256:
        raise ValueError(f"{archive.name} SHA-256 does not match the pin")
    wanted = {f"{spec.top_level}/{name}": name for name in spec.files}
    found: set[str] = set()
    with tarfile.open(archive, mode="r:bz2") as bundle:
        for member in bundle:
            name = wanted.get(member.name)
            if name is None:
                continue
            if not member.isreg() or name in found:
                raise ValueError(f"Unexpected archive member type or duplicate: {member.name}")
            if member.size > MAX_EXTRACTED_FILE_BYTES:
                raise ValueError(f"Archive member is too large: {member.name}")
            source = bundle.extractfile(member)
            if source is None:
                raise ValueError(f"Archive member is unreadable: {member.name}")
            with source, (staging / name).open("wb") as out:
                shutil.copyfileobj(source, out, 1024 * 1024)
            found.add(name)
    missing = sorted(set(spec.files) - found)
    if missing:
        raise ValueError(f"Archive lacks pinned files: {', '.join(missing)}")


def download_archive(spec: ArchiveSpec) -> list[dict[str, str]]:
    """Download, verify and extract a pinned archive; replace the destination atomically."""
    print(f"Downloading {spec.url} (sha256 {spec.sha256}) -> {spec.destination}")
    spec.destination.parent.mkdir(parents=True, exist_ok=True)
    revision = f"{spec.url}#sha256={spec.sha256}"
    with tempfile.TemporaryDirectory(dir=spec.destination.parent) as work:
        archive = Path(work) / "archive.tar.bz2"
        staging = Path(work) / "staging"
        staging.mkdir()
        fetch_archive(spec, archive)
        extract_archive(spec, archive, staging)
        if spec.destination.exists():
            shutil.rmtree(spec.destination)
        staging.replace(spec.destination)
    return [
        manifest_entry(spec.destination / name, spec.repo_id, revision)
        for name in sorted(spec.files)
    ]


def write_manifest(
    entries: list[dict[str, str]], *, replace_prefixes: tuple[str, ...] = ()
) -> None:
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    retained: list[dict[str, str]] = []
    if replace_prefixes and MANIFEST.exists():
        existing = json.loads(MANIFEST.read_text(encoding="utf-8"))
        retained = [
            item
            for item in existing.get("artifacts", [])
            if not any(item["path"].startswith(prefix) for prefix in replace_prefixes)
        ]
    by_path = {item["path"]: item for item in [*retained, *entries]}
    payload = {
        "schema_version": 1,
        "artifacts": sorted(by_path.values(), key=lambda item: item["path"]),
    }
    MANIFEST.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download all models once for subsequent offline operation."
    )
    parser.add_argument(
        "--component",
        choices=("all", "stt", "translation", "tts"),
        default="all",
        help="Optionally download only one model group.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        entries: list[dict[str, str]] = []
        if args.component in {"all", "stt"}:
            entries.extend(download_snapshot(FASTER_WHISPER))
        if args.component in {"all", "translation"}:
            for spec in MARIAN_SNAPSHOTS:
                entries.extend(download_snapshot(spec))
        if args.component in {"all", "tts"}:
            entries.extend(download_piper_file(spec) for spec in PIPER_VOICE_FILES)
            entries.extend(download_archive(SHERPA_MANDARIN_VOICE))
        replace_prefixes = {
            "all": (),
            "stt": ("models/faster-whisper-small/",),
            "translation": ("models/opus-mt-de-zh/", "models/opus-mt-zh-de/"),
            "tts": ("models/piper/", "models/sherpa/"),
        }[args.component]
        write_manifest(entries, replace_prefixes=replace_prefixes)
    except Exception as exc:  # noqa: BLE001 - CLI boundary returns one actionable error.
        print(f"Model download failed: {exc}", file=sys.stderr)
        return 1
    print("Downloaded artifacts are pinned and recorded in models/model-manifest.json.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
