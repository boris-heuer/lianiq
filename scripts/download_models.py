from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from huggingface_hub import hf_hub_download, snapshot_download

ROOT = Path(__file__).resolve().parent.parent
MODELS = ROOT / "models"


def download_snapshot(
    repo_id: str, destination: Path, allow_patterns: list[str] | None = None
) -> None:
    print(f"Downloading {repo_id} -> {destination}")
    destination.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        repo_id=repo_id,
        local_dir=destination,
        allow_patterns=allow_patterns,
    )


def download_piper_file(filename: str, destination: Path) -> None:
    print(f"Downloading rhasspy/piper-voices/{filename}")
    cached = Path(hf_hub_download(repo_id="rhasspy/piper-voices", filename=filename))
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(cached, destination)


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
        if args.component in {"all", "stt"}:
            download_snapshot("Systran/faster-whisper-small", MODELS / "faster-whisper-small")
        if args.component in {"all", "translation"}:
            marian_files = ["*.json", "*.spm", "pytorch_model.bin", "README.md"]
            download_snapshot(
                "Helsinki-NLP/opus-mt-de-zh",
                MODELS / "opus-mt-de-zh",
                allow_patterns=marian_files,
            )
            download_snapshot(
                "Helsinki-NLP/opus-mt-zh-de",
                MODELS / "opus-mt-zh-de",
                allow_patterns=marian_files,
            )
        if args.component in {"all", "tts"}:
            voices = {
                "de/de_DE/thorsten/medium/de_DE-thorsten-medium.onnx": (
                    MODELS / "piper" / "de_DE-thorsten-medium.onnx"
                ),
                "de/de_DE/thorsten/medium/de_DE-thorsten-medium.onnx.json": (
                    MODELS / "piper" / "de_DE-thorsten-medium.onnx.json"
                ),
                "zh/zh_CN/huayan/medium/zh_CN-huayan-medium.onnx": (
                    MODELS / "piper" / "zh_CN-huayan-medium.onnx"
                ),
                "zh/zh_CN/huayan/medium/zh_CN-huayan-medium.onnx.json": (
                    MODELS / "piper" / "zh_CN-huayan-medium.onnx.json"
                ),
            }
            for remote, local in voices.items():
                download_piper_file(remote, local)
    except Exception as exc:  # noqa: BLE001 - CLI boundary returns one actionable error.
        print(f"Model download failed: {exc}", file=sys.stderr)
        return 1
    print("Models are available locally. The application can now run offline.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
