"""``SHA256SUMS`` over every other file of an artifact folder (CAP-0174 contract §7.2).

The format is ``sha256sum``'s text form: ``<64 lower-case hex>  <relative/posix/path>``, one
line per file, sorted by path, LF line endings, UTF-8. ``verify_sums`` reports each
``changed``, ``missing`` and ``unlisted`` file and each ``malformed`` line, so a file added,
removed or altered after ``write_sums`` makes verification fail.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

SUMS_NAME = "SHA256SUMS"
_LINE = re.compile(r"^([0-9a-f]{64})  ((?!(?:.*/)?\.\.(?:/|$))[^/\\:][^\\:]*)$")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _files(root: Path) -> list[str]:
    return sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.relative_to(root).as_posix() != SUMS_NAME
    )


def write_sums(root: Path) -> Path:
    """Write ``root/SHA256SUMS`` listing every other file below ``root``; return its path."""
    lines = [f"{file_sha256(root / name)}  {name}\n" for name in _files(root)]
    target = root / SUMS_NAME
    target.write_text("".join(lines), encoding="utf-8", newline="\n")
    return target


def verify_sums(root: Path) -> list[str]:
    """Return one error per mismatch; an empty list means the folder verifies."""
    target = root / SUMS_NAME
    if not target.is_file():
        return [f"missing: {SUMS_NAME}"]
    errors: list[str] = []
    listed: dict[str, str] = {}
    for number, line in enumerate(target.read_text(encoding="utf-8").splitlines(), start=1):
        match = _LINE.match(line)
        if match is None or match.group(2) in listed:
            errors.append(f"malformed: line {number}")
            continue
        listed[match.group(2)] = match.group(1)
    present = set(_files(root))
    for name, digest in sorted(listed.items()):
        if name not in present:
            errors.append(f"missing: {name}")
        elif file_sha256(root / name) != digest:
            errors.append(f"changed: {name}")
    errors += [f"unlisted: {name}" for name in sorted(present - set(listed))]
    return errors
