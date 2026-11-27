"""The Listen transcript model, moved to ``lianiq.ui.transcript.model`` (paired-transcript).

The old names stay importable here.
"""

from __future__ import annotations

from lianiq.ui.transcript.model import (
    REASON_TEXT,
    STATE_TEXT,
    PairedTranscriptModel,
    reason_text,
    right_to_left,
)

ListenTranscriptModel = PairedTranscriptModel

__all__ = [
    "REASON_TEXT",
    "STATE_TEXT",
    "ListenTranscriptModel",
    "PairedTranscriptModel",
    "reason_text",
    "right_to_left",
]
