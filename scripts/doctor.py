from __future__ import annotations

import importlib.util
import json
import platform
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def status(ok: bool, name: str, detail: str = "") -> bool:
    marker = "OK " if ok else "MISSING"
    print(f"[{marker}] {name}{': ' + detail if detail else ''}")
    return ok


def main() -> int:
    checks: list[bool] = []
    checks.append(
        status(sys.version_info[:2] in {(3, 11), (3, 12)}, "Python", platform.python_version())
    )
    for module in ("numpy", "sounddevice", "faster_whisper", "transformers", "torch", "PySide6"):
        checks.append(
            status(importlib.util.find_spec(module) is not None, f"Python module {module}")
        )
    checks.append(status(importlib.util.find_spec("piper") is not None, "Python module piper"))

    expected = [
        ROOT / "models" / "faster-whisper-small" / "model.bin",
        ROOT / "models" / "opus-mt-de-zh" / "config.json",
        ROOT / "models" / "opus-mt-zh-de" / "config.json",
        ROOT / "models" / "piper" / "de_DE-thorsten-medium.onnx",
        ROOT / "models" / "piper" / "de_DE-thorsten-medium.onnx.json",
        ROOT / "models" / "piper" / "zh_CN-huayan-medium.onnx",
        ROOT / "models" / "piper" / "zh_CN-huayan-medium.onnx.json",
    ]
    for path in expected:
        checks.append(
            status(path.exists() and path.stat().st_size > 0, str(path.relative_to(ROOT)))
        )

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
