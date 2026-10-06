from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
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
        replace_prefixes = {
            "all": (),
            "stt": ("models/faster-whisper-small/",),
            "translation": ("models/opus-mt-de-zh/", "models/opus-mt-zh-de/"),
            "tts": ("models/piper/",),
        }[args.component]
        write_manifest(entries, replace_prefixes=replace_prefixes)
    except Exception as exc:  # noqa: BLE001 - CLI boundary returns one actionable error.
        print(f"Model download failed: {exc}", file=sys.stderr)
        return 1
    print("Downloaded artifacts are pinned and recorded in models/model-manifest.json.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
