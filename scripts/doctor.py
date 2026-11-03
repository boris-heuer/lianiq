from __future__ import annotations

import argparse
import importlib.util
import json
import platform
import sys
from pathlib import Path

from lianiq.config import AppConfig
from lianiq.languages import (
    BUILTIN_REGISTRY,
    CapabilityCatalog,
    DirectedEdge,
    LanguageContractError,
    LanguageRegistry,
    ReadinessProbe,
    ReadinessStatus,
)

ROOT = Path(__file__).resolve().parent.parent


def status(ok: bool, name: str, detail: str = "") -> bool:
    marker = "OK " if ok else "MISSING"
    print(f"[{marker}] {name}{': ' + detail if detail else ''}")
    return ok


def warn(name: str, detail: str) -> None:
    print(f"[WARN] {name}: {detail}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate a lianiq installation.")
    parser.add_argument(
        "--require-voices",
        action="store_true",
        help=(
            "Fail unless the voice of every language in the configured pair is provisioned "
            "(operational spoken-output verification)."
        ),
    )
    return parser.parse_args(argv)


def _voice_metadata_present(voice_path: Path | None) -> bool:
    return voice_path is not None and Path(f"{voice_path}.json").is_file()


def check_capabilities(
    config: AppConfig,
    *,
    require_voices: bool,
    root: Path | None = None,
    registry: LanguageRegistry = BUILTIN_REGISTRY,
) -> list[bool]:
    """Print the readiness of each capability of the configured language pair.

    Recognition of both pair languages and translation in both directions are required.
    A voice is optional (spoken output stays unavailable without it) unless
    ``require_voices`` is set; a voice whose files do not match the manifest always fails.
    """
    probe = ReadinessProbe(ROOT if root is None else root)
    try:
        pair = registry.pair(*config.languages.pair)
        catalog = CapabilityCatalog.from_config(config, registry, probe)
    except (LanguageContractError, TypeError, ValueError) as error:
        return [status(False, "Language pair", str(error))]

    def name(language: str) -> str:
        return f"{language} ({registry.display_name(language)})"

    checks = [status(True, "Language pair", f"{name(pair.first)} ↔ {name(pair.second)}")]
    if probe.manifest_problem is not None:
        warn("Model manifest", f"{probe.manifest_problem}; files are checked without it")

    for language in pair.members:
        capability = catalog.recognition(language)
        checks.append(
            status(
                capability.status.is_ready,
                f"recognition {name(language)}",
                capability.status.value,
            )
        )
    for source in pair.members:
        edge = DirectedEdge(source, pair.other(source))
        capability = catalog.translation(edge)
        label = (
            f"translation {edge.key} "
            f"({registry.display_name(edge.source)} → {registry.display_name(edge.target)})"
        )
        checks.append(status(capability.status.is_ready, label, capability.status.value))
    for language in pair.members:
        capability = catalog.voice(language)
        label = f"voice {name(language)}"
        detail = capability.status.value
        if capability.status.is_ready and not _voice_metadata_present(capability.voice_path):
            detail = "missing metadata file (.onnx.json)"
        elif capability.status.is_ready:
            checks.append(status(True, label, detail))
            continue
        if capability.status is ReadinessStatus.INVALID or require_voices:
            checks.append(status(False, label, detail))
        else:
            warn(label, f"{detail}; spoken output in this language stays unavailable")
    return checks


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = parse_args(argv)
    checks: list[bool] = []
    checks.append(status(sys.version_info[:2] == (3, 12), "Python", platform.python_version()))
    for module in ("numpy", "sounddevice", "faster_whisper", "transformers", "torch", "PySide6"):
        checks.append(
            status(importlib.util.find_spec(module) is not None, f"Python module {module}")
        )
    checks.append(status(importlib.util.find_spec("piper") is not None, "Python module piper"))

    try:
        config = AppConfig.load()
    except Exception as exc:  # noqa: BLE001 - diagnostic must summarize unreadable settings.
        checks.append(status(False, "Settings", str(exc)))
    else:
        checks.append(status(True, "Settings", f"schema v{config.schema_version}"))
        checks.extend(check_capabilities(config, require_voices=args.require_voices))

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
