"""Listen transcript rows (CAP-0170 contract.md §3), now the shared turn log.

The rows moved to ``lianiq.transcript.turns`` (paired-transcript spec §3.1); the old names
stay importable here.
"""

from __future__ import annotations

from lianiq.transcript.turns import OPEN_STATES, Turn, TurnLog, TurnState

ListenTranscript = TurnLog
Segment = Turn
SegmentState = TurnState

__all__ = ["OPEN_STATES", "ListenTranscript", "Segment", "SegmentState"]
