"""Download every language pack once for offline use (a thin CLI over ``lianiq.packs``).

The pins (URLs, sizes, SHA-256) live in ``lianiq/packs/builtin_catalog.json``. Each pack is
installed through the app's staged ``PackInstaller`` and recorded with ``source: "script"``
and no licence acceptance time (CAP-0171 contract.md §3), so the app shows it *Validated*.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lianiq.languages import BUILTIN_REGISTRY
from lianiq.packs.catalog import (
    BUILTIN_CATALOG_PATH,
    PackCatalog,
    PackDefinition,
    PackKind,
)
from lianiq.packs.installer import InstallResult, PackInstaller
from lianiq.packs.jobs import CancelToken, JobPhase
from lianiq.packs.sources import DownloadSource, HttpsTransport, Transport

COMPONENTS: dict[str, tuple[PackKind, ...]] = {
    "all": tuple(PackKind),
    "stt": (PackKind.RECOGNITION,),
    "translation": (PackKind.TRANSLATION,),
    "tts": (PackKind.VOICE,),
}
MANIFEST_NAME = "model-manifest.json"


def load_catalog() -> PackCatalog:
    return PackCatalog.load(BUILTIN_CATALOG_PATH, BUILTIN_REGISTRY)


def selected_packs(catalog: PackCatalog, component: str) -> tuple[PackDefinition, ...]:
    kinds = COMPONENTS[component]
    return tuple(pack for pack in catalog.packs() if pack.kind in kinds)


def _printer(pack: PackDefinition) -> Callable[[JobPhase, int, int], None]:
    shown: set[JobPhase] = set()

    def progress(phase: JobPhase, done: int, total: int) -> None:
        if phase not in shown:
            shown.add(phase)
            print(f"  {pack.id}: {phase.value}")

    return progress


def install_packs(
    component: str = "all",
    *,
    root: Path = ROOT,
    catalog: PackCatalog | None = None,
    transport: Transport | None = None,
    clock: Callable[[], datetime] | None = None,
) -> list[InstallResult]:
    """Install the packs of ``component``; the first failure raises."""
    catalog = catalog or load_catalog()
    installer = PackInstaller(
        root,
        root / "models" / MANIFEST_NAME,
        clock or (lambda: datetime.now().astimezone()),
        catalog=catalog,
    )
    installer.recover()
    source = DownloadSource(transport or HttpsTransport(), record_source="script")
    results = []
    for pack in selected_packs(catalog, component):
        print(f"Downloading {pack.id} {pack.version} ({pack.download_bytes} bytes) -> {pack.root}")
        results.append(installer.install(pack, source, None, _printer(pack), CancelToken()))
        print(f"Installed {pack.id} {pack.version}")
    return results


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download all models once for subsequent offline operation."
    )
    parser.add_argument(
        "--component",
        choices=tuple(COMPONENTS),
        default="all",
        help="Optionally download only one model group.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        install_packs(args.component, root=ROOT, catalog=load_catalog(), transport=HttpsTransport())
    except Exception as exc:  # noqa: BLE001 - CLI boundary returns one actionable error.
        print(f"Model download failed: {exc}", file=sys.stderr)
        return 1
    print(f"Downloaded packs are pinned and recorded in models/{MANIFEST_NAME}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
