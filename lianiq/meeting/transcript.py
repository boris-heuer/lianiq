"""The meeting's text transcript (CAP-0177 contract.md §5, spec AC-16 and AC-17).

Qt-free. The text is the CAP-0169 transcript v2 of the translated contributions: both
directions, both languages per turn, ordered by speech end (``captured_at``) like the running
view. It is written only after the PO's consent, as UTF-8 text at the chosen path with an
atomic replace; audio is never written. A write error propagates as ``OSError`` to the page,
which shows a notice naming the reason; a failed write leaves no partial file behind.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterable
from pathlib import Path

from lianiq.domain import TranslationResult
from lianiq.languages.registry import LanguagePair
from lianiq.languages.session import format_transcript_v2


def meeting_transcript_text(pair: LanguagePair, results: Iterable[TranslationResult]) -> str:
    return format_transcript_v2(pair, results)


def write_meeting_transcript(path: Path, text: str) -> None:
    """Write ``text`` as UTF-8 (LF line ends) to ``path``, replacing it atomically."""
    path = Path(path)
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
