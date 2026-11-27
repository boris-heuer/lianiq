"""Source length rule (contract.md §2).

The counted text is the editor's plain text, where every line break is one ``\n``. Every
Unicode code point counts: spaces, line breaks, combining marks and each code point of an
emoji sequence. One Han character counts one.

The limit bounds memory and run time of one request (CAP-0172 rev 1.1, lianiq#35): a long text
is translated in bounded segments (``segments.py``) with progress and cancel at each segment.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final

MAX_SOURCE_CODE_POINTS: Final = 50_000


class SourceCheck(StrEnum):
    OK = "ok"
    EMPTY = "empty"
    TOO_LONG = "too_long"


def source_length(text: str) -> int:
    """The length of ``text`` in Unicode code points."""
    return len(text)


def check_source(text: str) -> SourceCheck:
    if not text.strip():
        return SourceCheck.EMPTY
    if source_length(text) > MAX_SOURCE_CODE_POINTS:
        return SourceCheck.TOO_LONG
    return SourceCheck.OK
