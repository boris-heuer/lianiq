"""Scratch ``models`` folders for rows that need an empty or imported pack set (spec §2.1.1).

The checkout's ``models`` is a junction to the image's read-only ``models_dir`` (workflow
step "Install the checkout into the image environment"). ``scratch_models(ctx, group)`` points
it at a new, empty, writable folder ``%TEMP%\\lianiq-e2e\\models-<group>`` (one per group of
scratch-model rows, not per row) and points it back at ``models_dir`` in ``finally``, also
when a row raises. A junction is removed with
``os.rmdir``, which deletes the link only and never the target; a real folder named
``models`` is never removed (``RuntimeError``). Every scratch folder is recorded in
``ctx.state["models_scratch"]``; T-05 checks the junction once more and deletes them.

The app must be closed on entry and on exit: an open model file keeps the old target busy.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from native_e2e.context import RunContext

SCRATCH_KEY = "models_scratch"
_PREFIXES = ("\\\\?\\", "\\??\\")


def link_path(ctx: RunContext) -> Path:
    """The checkout's ``models`` junction."""
    return ctx.repo / "models"


def image_models(ctx: RunContext) -> Path:
    """The image's read-only models folder (``image.json`` ``models_dir``)."""
    return Path(str(ctx.image()["models_dir"]))


def _norm(path: str | Path) -> str:
    text = str(path)
    for prefix in _PREFIXES:
        text = text.removeprefix(prefix)
    return os.path.normcase(os.path.normpath(text))


def target(link: Path) -> str | None:
    """The folder the junction ``link`` points at, or ``None`` when it is no junction."""
    if not link.is_junction():
        return None
    return _norm(os.readlink(link))


def points_to(link: Path, folder: Path) -> bool:
    current = target(link)
    return current is not None and current == _norm(folder)


def repoint(link: Path, folder: Path) -> None:
    """Make ``link`` a junction to ``folder``; an existing junction is unlinked first."""
    if link.is_junction():
        os.rmdir(link)  # removes the junction only
    elif link.exists():
        raise RuntimeError("models is not a junction")
    import _winapi

    _winapi.CreateJunction(str(folder), str(link))


def restore(ctx: RunContext) -> bool:
    """Point the junction at the image models again (if needed); whether it does now."""
    link, models = link_path(ctx), image_models(ctx)
    if not points_to(link, models):
        repoint(link, models)
    return points_to(link, models)


def scratch_folder(ctx: RunContext, group: str) -> Path:
    """A new, empty scratch folder for ``group`` (an older one of the same name is deleted)."""
    folder = ctx.temp / f"models-{group}"
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    recorded = ctx.state.setdefault(SCRATCH_KEY, [])
    if str(folder) not in recorded:
        recorded.append(str(folder))
    return folder


@contextmanager
def scratch_models(ctx: RunContext, group: str) -> Iterator[Path]:
    """Point ``models`` at an empty scratch folder for the block; restore it afterwards."""
    link = link_path(ctx)
    image_models(ctx)  # a missing image.json raises before anything changes
    folder = scratch_folder(ctx, group)
    try:
        repoint(link, folder)  # inside the try: a failed CreateJunction after the unlink
        yield folder  # still gets the image junction back
    finally:
        restore(ctx)


def delete_scratch(ctx: RunContext) -> list[str]:
    """Delete every recorded scratch folder; the ones still present afterwards."""
    left: list[str] = []
    link = link_path(ctx)
    for name in ctx.state.get(SCRATCH_KEY, []):
        folder = Path(name)
        if points_to(link, folder):
            left.append(name)  # never delete what the checkout still uses
            continue
        shutil.rmtree(folder, ignore_errors=True)
        if folder.exists():
            left.append(name)
    return left
