"""Pair-scoped, stateless turn routing (CAP-0169 contract.md §3.1.5)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from lianiq.domain import Transcript
from lianiq.languages.modes import RoutingKind, SessionPair
from lianiq.languages.registry import LanguageId

HeldReason = Literal["low_confidence", "out_of_pair", "unregistered"]


@dataclass(frozen=True, slots=True)
class TurnRoute:
    source: LanguageId
    target: LanguageId


@dataclass(frozen=True, slots=True)
class HeldTurn:
    """A turn whose spoken language is unclear; nothing is translated until it is resolved."""

    turn_id: UUID
    captured_at: datetime
    transcript: Transcript
    reason: HeldReason


def _now() -> datetime:
    return datetime.now().astimezone()


class TurnRouter:
    """Resolve every utterance independently; never assume alternating speakers.

    Fixed routing translates from the fixed source without detection. Bidirectional
    routing translates only a detected pair member at or above ``min_probability``;
    any other turn is held. No call depends on an earlier one.
    """

    def __init__(self, min_probability: float) -> None:
        if not 0.0 <= min_probability <= 1.0:
            raise ValueError("min_probability must be between 0 and 1")
        self.min_probability = min_probability

    def route(
        self,
        session: SessionPair,
        transcript: Transcript,
        *,
        turn_id: UUID | None = None,
        captured_at: datetime | None = None,
    ) -> TurnRoute | HeldTurn:
        """Route one turn; ``turn_id``/``captured_at`` identify a held turn (default: new)."""
        pair = session.pair
        if session.mode.routing is RoutingKind.FIXED:
            source = session.fixed_source
            assert source is not None  # SessionPair guarantees it for fixed routing
            return TurnRoute(source, pair.other(source))
        detected = transcript.language
        reason: HeldReason | None = None
        if detected is None:
            reason = "unregistered"
        elif detected not in pair:
            reason = "out_of_pair"
        elif transcript.probability < self.min_probability:
            reason = "low_confidence"
        if reason is None:
            return TurnRoute(detected, pair.other(detected))
        return HeldTurn(
            turn_id=turn_id or uuid4(),
            captured_at=captured_at or _now(),
            transcript=transcript,
            reason=reason,
        )
