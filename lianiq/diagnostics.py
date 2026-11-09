"""The local diagnostics log and its pattern redaction (CAP-0168 contract.md §5).

Qt-free and offline: the log lives in memory only and leaves the app only through an
explicit **Copy** or **Export…** in Settings › Diagnostics, always as ``export_text()``.
Callers record what happened (notice keys and titles, session states, turn IDs, languages,
timings), never transcript text.

``redact`` works by pattern, not by a list of known values:

- every endpoint identity (``windows-mmdevice:v1:…``, ``audio-endpoint:v1:…`` and raw
  MMDevice ``{0.0.x.00000000}.{guid}`` strings) becomes ``<endpoint-N>``, numbered in order
  of first appearance within one call, so the same identity keeps one number;
- the home path becomes ``~`` (only where a separator, quote, whitespace or the end follows,
  so ``C:\\Users\\jdoe2`` or the short name ``JDOE~1`` is not a home path); then every
  absolute path (drive letter, UNC, POSIX) and every ``~`` path becomes
  ``<path>/<last component>``. Inner components may contain spaces when another separator
  follows (``Program Files``, ``OneDrive - Contoso GmbH``); the last component ends at
  whitespace or a quote; a quoted path is one path, spaces and all;
- the username becomes ``<user>``.
"""

from __future__ import annotations

import getpass
import re
from collections import deque
from datetime import datetime
from pathlib import Path

_ENDPOINT_ID = re.compile(
    r"(?:windows-mmdevice|audio-endpoint):v1:[A-Za-z0-9_.:#{}\-]+"
    r"|\{\d+\.\d+\.\d+\.[0-9A-Fa-f]{8}\}\.\{[0-9A-Fa-f-]{36}\}"
)
_CHAR = r"[^\s\\/\"'<>|*?:]"  # a path character: no separator, quote, colon or whitespace
_SEGMENT = rf"{_CHAR}+"
# An inner component: words joined by single spaces, always followed by a separator.
_INNER = rf"{_CHAR}+(?: {_CHAR}+)*"
_SEPARATOR = r"[\\/]+"
# Drive letter (C:\…, C:/…), UNC (\\server\share\…) or ~ (after home replacement).
_WINDOWS_START = rf"(?:\b[A-Za-z]:{_SEPARATOR}|\\\\{_SEGMENT}\\+|(?<![\w~])~{_SEPARATOR})"
# POSIX: a leading slash that does not follow a word, a scheme, a placeholder or a path.
_POSIX_START = r"(?<![\w:/\\.~<>])/"
_ABSOLUTE_PATH = re.compile(
    rf"(?:{_WINDOWS_START}|{_POSIX_START})(?:{_INNER}{_SEPARATOR})*(?:{_SEGMENT})?"
)
# A quoted absolute path is one path, whatever spaces it contains.
_QUOTED_PATH = re.compile(
    rf"(?P<quote>['\"])(?P<path>(?:{_WINDOWS_START}|{_POSIX_START})[^'\"\r\n]*)(?P=quote)"
)


def redact(text: str, *, home: Path, username: str) -> str:
    """``text`` without endpoint IDs, absolute paths, the home path and the username."""
    numbers: dict[str, int] = {}

    def endpoint(match: re.Match[str]) -> str:
        number = numbers.setdefault(match.group(0), len(numbers) + 1)
        return f"<endpoint-{number}>"

    text = _ENDPOINT_ID.sub(endpoint, text)
    for spelling in _home_spellings(home):
        # Only the whole home folder: not ``jdoe2`` or the short name ``JDOE~1``.
        pattern = rf"{re.escape(spelling)}(?=[\\/'\"]|\s|$)"
        text = re.sub(pattern, "~", text, flags=re.IGNORECASE)
    text = _QUOTED_PATH.sub(
        lambda match: match.group("quote") + _shorten(match.group("path")) + match.group("quote"),
        text,
    )
    text = _ABSOLUTE_PATH.sub(lambda match: _shorten(match.group(0)), text)
    if username:
        text = re.sub(rf"(?<!\w){re.escape(username)}(?!\w)", "<user>", text, flags=re.IGNORECASE)
    return text


def _home_spellings(home: Path) -> list[str]:
    raw = str(home).rstrip("\\/")
    if len(raw) < 2:  # "/" or "" is no home path worth replacing
        return []
    backslashed = raw.replace("/", "\\")
    # Also the doubled backslashes of a ``repr`` (an ``OSError`` message).
    spellings = {raw, raw.replace("\\", "/"), backslashed, backslashed.replace("\\", "\\\\")}
    return sorted(spellings, key=len, reverse=True)


def _shorten(path: str) -> str:
    parts = [part for part in re.split(r"[\\/]+", path.strip()) if part]
    last = parts[-1] if parts else ""
    if not last or re.fullmatch(r"[A-Za-z]:|~", last):
        return "<path>"
    return f"<path>/{last}"


class DiagnosticsLog:
    """A bounded in-memory log; ``export_text`` is the only way out (Copy and Export…)."""

    def __init__(
        self,
        capacity: int = 500,
        *,
        home: Path | None = None,
        username: str | None = None,
    ) -> None:
        self._entries: deque[tuple[datetime, str, str]] = deque(maxlen=capacity)
        self._home = home
        self._username = username

    def record(self, category: str, message: str) -> None:
        self._entries.append((datetime.now().astimezone(), category, message))

    def entries(self) -> tuple[tuple[datetime, str, str], ...]:
        return tuple(self._entries)

    def export_text(self) -> str:
        """Every entry, one per line, redacted as one text (stable endpoint numbering)."""
        lines = [
            f"{when.isoformat(timespec='seconds')} [{category}] {message}"
            for when, category, message in self._entries
        ]
        return self.redact("\n".join(lines) + ("\n" if lines else ""))

    def redact(self, text: str) -> str:
        """``redact`` with this log's home path and username (e.g. an export error)."""
        return redact(
            text,
            home=self._home if self._home is not None else Path.home(),
            username=self._username if self._username is not None else _current_user(),
        )


def _current_user() -> str:
    try:
        return getpass.getuser()
    except Exception:  # noqa: BLE001 - no user name known: nothing to replace.
        return ""
