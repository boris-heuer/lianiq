"""Safe relative pack paths (CAP-0171 contract.md §1, §2). Qt-free, standard library only.

A listed path, a pack root and an archive's top level must stay inside their base on every
platform Lianiq writes to. On Windows that also excludes control characters, the reserved
device names and segments that Windows silently trims (trailing dot or space).
"""

from __future__ import annotations

import re

# Device names in any folder, with any extension: CON, PRN, AUX, NUL, CONIN$, CONOUT$,
# COM0-9 and LPT0-9, and COM/LPT with a superscript one, two or three (Windows treats them
# as COM1-3 and LPT1-3).
_RESERVED = re.compile(
    r"(?:CON|PRN|AUX|NUL|CONIN\$|CONOUT\$|COM[0-9¹²³]|LPT[0-9¹²³])",
    re.IGNORECASE,
)


def _control(text: str) -> bool:
    return any(ord(char) < 0x20 or ord(char) == 0x7F for char in text)


def _safe_segment(part: str) -> bool:
    if part in ("", ".", "..") or part[-1] in ". ":
        return False
    stem = part.split(".", 1)[0].rstrip(" ")
    return _RESERVED.fullmatch(stem) is None


def is_safe_relative(path: object) -> bool:
    """A non-empty POSIX path that stays below its base on Windows and POSIX.

    Rejected: a non-string, a drive (``:``), a leading ``/``, a backslash, NUL or another
    control character, an empty, ``.`` or ``..`` segment, a segment ending in a dot or a
    space, and a Windows reserved device name as any segment (``con``, ``NUL.txt``).
    """
    if not isinstance(path, str) or not path or "\\" in path or ":" in path:
        return False
    if path[0] == "/" or _control(path):
        return False
    return all(_safe_segment(part) for part in path.split("/"))
