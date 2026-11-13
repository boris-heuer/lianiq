"""Redaction gate for the native evidence artifact (CAP-0174 contract §1, §6 and §7.2).

``scan`` reports one ``Finding(file, pattern_class)`` per file and pattern class and never
the matched text. ``mask`` blacks out screenshot rectangles (for example endpoint names)
before the PNG is written. The module is Qt-free; only ``mask`` imports QImage, lazily.

Pattern classes:

- ``username``: ``%USERNAME%`` as a whole token (``e2e`` inside ``native-e2e`` is not one);
- ``profile-path``: ``%USERPROFILE%`` or any ``<drive>:\\Users\\<name>`` path;
- ``drive-path``: any absolute drive path ``<letter>:\\`` or ``<letter>:/``;
- ``endpoint-id``: a Windows audio endpoint identifier ``{0.0.0.`` / ``{0.0.1.``;
- ``secret``: any given string (endpoint names, transcript texts, test phrase, canary),
  compared case-insensitively;
- ``audio-pcm``: a RIFF/WAVE file or a ``.wav``/``.pcm``/``.raw`` file.

PNG files are not text-scanned: screenshots are masked instead.

``Finding.file`` is the given path in POSIX form, unchanged. Findings go into the job
summary, so callers must pass paths relative to the artifact root (never absolute ones).
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PySide6.QtCore import QRect

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
AUDIO_SUFFIXES = frozenset({".wav", ".pcm", ".raw"})
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("drive-path", re.compile(r"(?<![A-Za-z])[A-Za-z]:[\\/]")),
    ("endpoint-id", re.compile(r"\{0\.0\.[01]\.")),
    ("profile-path", re.compile(r"(?<![A-Za-z])[A-Za-z]:[\\/]+Users[\\/]+[^\\/\s]", re.IGNORECASE)),
)


# Whole token: not glued to a preceding word, "-" or "word." ("native-e2e", "a.e2e") and not
# followed by a word character or ".word" ("e2e.log"); "as e2e." and "e2e-x" still match.
_USER = r"(?<![\w-])(?<!\w\.){}(?!\w)(?!\.\w)"


@dataclass(frozen=True)
class Finding:
    file: str
    pattern_class: str


def scan(paths: Iterable[Path], secrets: Iterable[str]) -> list[Finding]:
    """Return the findings per file, sorted by pattern class within each file."""
    needles = [secret.casefold() for secret in secrets if secret]
    username = os.environ.get("USERNAME", "")
    profile = os.environ.get("USERPROFILE", "").casefold()
    findings: list[Finding] = []
    for path in paths:
        classes = _classes(Path(path), needles, username, profile)
        findings += [Finding(Path(path).as_posix(), name) for name in sorted(classes)]
    return findings


def _classes(path: Path, needles: list[str], username: str, profile: str) -> set[str]:
    data = path.read_bytes()
    if path.suffix.lower() in AUDIO_SUFFIXES or (data[:4] == b"RIFF" and data[8:12] == b"WAVE"):
        return {"audio-pcm"}
    if data.startswith(PNG_SIGNATURE):
        return set()
    text = _decode(data)
    folded = text.casefold()
    classes = {name for name, pattern in _PATTERNS if pattern.search(text)}
    if profile and profile in folded:
        classes.add("profile-path")
    if username and re.search(_USER.format(re.escape(username)), text, re.IGNORECASE):
        classes.add("username")
    if any(needle in folded for needle in needles):
        classes.add("secret")
    return classes


def _decode(data: bytes) -> str:
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", errors="replace")
    return data.decode("utf-8-sig", errors="replace")


def mask(png: bytes, rects: Iterable[QRect]) -> bytes:
    """Return ``png`` with every rectangle filled opaque black (clipped to the image)."""
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    from PySide6.QtGui import QColor, QImage, QPainter

    image = QImage.fromData(png, "PNG")
    if image.isNull():
        raise ValueError("mask: input is not a readable PNG image")
    image = image.convertToFormat(QImage.Format.Format_ARGB32)
    painter = QPainter(image)
    try:
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        for rect in rects:
            painter.fillRect(rect.intersected(image.rect()), QColor(0, 0, 0, 255))
    finally:
        painter.end()
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not image.save(buffer, "PNG"):
        raise ValueError("mask: the masked image could not be encoded")
    buffer.close()
    return bytes(data)
