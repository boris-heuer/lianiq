from __future__ import annotations

from dataclasses import dataclass

from lianiq.domain import ConversationMode, Language


@dataclass(frozen=True, slots=True)
class TurnRoute:
    source: Language
    target: Language


class TurnRouter:
    """Resolve every utterance independently; never assume alternating speakers."""

    def route(self, mode: ConversationMode, detected_language: Language) -> TurnRoute:
        source = mode.forced_source or detected_language
        return TurnRoute(source=source, target=source.other)
