from __future__ import annotations

import argparse
import importlib.util
import json
import platform
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

REQUIRED_MODEL_PATHS = (
    "models/faster-whisper-small/model.bin",
    "models/opus-mt-de-zh/config.json",
    "models/opus-mt-zh-de/config.json",
    "models/piper/de_DE-thorsten-medium.onnx",
    "models/piper/de_DE-thorsten-medium.onnx.json",
)
MANDARIN_VOICE_PATHS = (
    "models/piper/zh_CN-user-provided.onnx",
    "models/piper/zh_CN-user-provided.onnx.json",
)


def status(ok: bool, name: str, detail: str = "") -> bool:
    marker = "OK " if ok else "MISSING"
    print(f"[{marker}] {name}{': ' + detail if detail else ''}")
    return ok


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate a lianiq installation.")
    parser.add_argument(
        "--require-mandarin-voice",
        action="store_true",
        help="Fail unless a separately reviewed Mandarin Piper voice is provisioned.",
    )
    return parser.parse_args(argv)


def check_models(require_mandarin_voice: bool) -> list[bool]:
    checks = []
    for relative in REQUIRED_MODEL_PATHS:
        path = ROOT / relative
        checks.append(status(path.exists() and path.stat().st_size > 0, relative))

    mandarin_ready = all(
        (ROOT / relative).exists() and (ROOT / relative).stat().st_size > 0
        for relative in MANDARIN_VOICE_PATHS
    )
    if require_mandarin_voice:
        checks.append(
            status(
                mandarin_ready,
                "User-provided Mandarin Piper voice",
                "required for operational spoken-output verification",
            )
        )
    elif mandarin_ready:
        checks.append(status(True, "User-provided Mandarin Piper voice"))
    else:
        print(
            "[WARN] User-provided Mandarin Piper voice: not provisioned; "
            "spoken output remains disabled by default"
        )
    return checks


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    checks: list[bool] = []
    checks.append(status(sys.version_info[:2] == (3, 12), "Python", platform.python_version()))
    for module in ("numpy", "sounddevice", "faster_whisper", "transformers", "torch", "PySide6"):
        checks.append(
            status(importlib.util.find_spec(module) is not None, f"Python module {module}")
        )
    checks.append(status(importlib.util.find_spec("piper") is not None, "Python module piper"))

    checks.extend(check_models(args.require_mandarin_voice))

    glossary = ROOT / "config" / "glossary.json"
    try:
        json.loads(glossary.read_text(encoding="utf-8"))
        checks.append(status(True, "Glossary JSON"))
    except Exception as exc:  # noqa: BLE001 - diagnostic must summarize malformed files.
        checks.append(status(False, "Glossary JSON", str(exc)))

    print(f"\n{sum(checks)}/{len(checks)} checks passed.")
    return 0 if all(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
