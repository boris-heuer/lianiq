"""The ``pack_files`` rule of ``ReadinessProbe`` (CAP-0171 contract.md §4). Qt-free.

Additive amendment of ``lianiq.language.readiness-status.v1``. ``pack_files`` maps a
resolved default capability path (a directory such as ``models/opus-mt-de-zh`` or a file
such as ``models/piper/de_DE-thorsten-medium.onnx``; POSIX, relative to the project root)
to every listed file of its pack, each ``PackFile.path`` also relative to the project root.
A capability at such a path is ``missing`` when a listed file is absent, ``invalid`` when one
has the wrong size or digest, else ``validated`` when every listed file has an artifact
record of a ``packs[]`` pack and ``installed`` otherwise. Every other path keeps the
CAP-0169 rules. The result is a ``ReadinessStatus`` value, so this module needs no import
of ``capabilities``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from lianiq.packs.verify import PackVerifier

if TYPE_CHECKING:
    from lianiq.packs.catalog import PackFile

PackFiles = Mapping[str, "tuple[PackFile, ...]"]


def normalize_key(path: str) -> str:
    return "/".join(part for part in path.replace("\\", "/").split("/") if part)


def normalize_pack_files(pack_files: PackFiles | None) -> dict[str, tuple[PackFile, ...]]:
    return {normalize_key(key): tuple(files) for key, files in (pack_files or {}).items()}


def pack_owned_paths(payload: Any) -> frozenset[str]:
    """Artifact paths whose ``pack_id`` names a ``packs[]`` record of the manifest payload."""
    if not isinstance(payload, dict):
        return frozenset()
    packs = payload.get("packs")
    ids = {
        item.get("id")
        for item in (packs if isinstance(packs, list) else ())
        if isinstance(item, dict)
    }
    artifacts = payload.get("artifacts")
    return frozenset(
        item["path"]
        for item in (artifacts if isinstance(artifacts, list) else ())
        if isinstance(item, dict)
        and isinstance(item.get("path"), str)
        and item.get("pack_id") in ids - {None}
    )


def listed_status(
    files: tuple[PackFile, ...],
    root: Path,
    owned: frozenset[str],
    verifier: PackVerifier,
    digests: Mapping[str, str] | None = None,
) -> str:
    """The ``ReadinessStatus`` value of a capability judged by its listed pack files.

    A listed file's digest is its manifest record (``digests``, by path) when one exists,
    otherwise the listed digest, as in ``lianiq.packs.state.pack_status``.
    """
    report = verifier.inspect(root, files, digests=False)
    if report.missing:
        return "missing"
    expected = {item.path: digests[item.path] for item in files if item.path in (digests or {})}
    if report.wrong_size or not verifier.inspect(root, files, expected).ok:
        return "invalid"
    return "validated" if all(item.path in owned for item in files) else "installed"


class PackRule:
    """The ``pack_files`` of one ``ReadinessProbe`` and the pack-owned manifest paths."""

    def __init__(self, pack_files: PackFiles | None) -> None:
        self.files = normalize_pack_files(pack_files)
        self.owned = frozenset[str]()

    def load(self, payload: Any) -> None:
        """Called by the probe for every manifest payload it loads."""
        self.owned = pack_owned_paths(payload)

    def status(
        self,
        path: Path,
        relative: Callable[[Path], str | None],
        records: Callable[[], Mapping[str, str]],
        root: Path,
        verifier: PackVerifier,
    ) -> str | None:
        """The status value of ``path`` under the pack rule, or ``None`` for a custom path.

        ``records`` loads the manifest (artifact digests by path), which also calls ``load``.
        """
        if not self.files:
            return None
        key = relative(path)
        files = None if key is None else self.files.get(key)
        if files is None:
            return None
        digests = records()
        return listed_status(files, root, self.owned, verifier, digests)
