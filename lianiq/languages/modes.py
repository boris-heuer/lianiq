"""Usage modes and the session pair (contract.md §3.1.3)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from lianiq.languages.errors import UnsupportedModeError
from lianiq.languages.registry import LanguageId, LanguagePair


class InputKind(str, Enum):
    TYPED = "typed"
    MICROPHONE = "microphone"


class RoutingKind(str, Enum):
    FIXED = "fixed"
    BIDIRECTIONAL = "bidirectional"


class OutputKind(str, Enum):
    TEXT = "text"
    SPOKEN = "spoken"


@dataclass(frozen=True, slots=True)
class UsageMode:
    input: InputKind
    routing: RoutingKind
    output: OutputKind
    call_bridge: bool = False  # implies MICROPHONE / BIDIRECTIONAL / SPOKEN
    meeting: bool = False  # implies MICROPHONE / BIDIRECTIONAL / SPOKEN; not with call_bridge

    def __post_init__(self) -> None:
        spoken_bidirectional_microphone = (
            self.input is InputKind.MICROPHONE
            and self.routing is RoutingKind.BIDIRECTIONAL
            and self.output is OutputKind.SPOKEN
        )
        if self.call_bridge and not spoken_bidirectional_microphone:
            raise UnsupportedModeError("Call Bridge implies microphone, bidirectional, spoken")
        if self.meeting and not spoken_bidirectional_microphone:
            raise UnsupportedModeError("Meeting implies microphone, bidirectional, spoken")
        if self.meeting and self.call_bridge:
            raise UnsupportedModeError("A mode cannot be both Call Bridge and Meeting")


CALL_BRIDGE_MODE = UsageMode(
    InputKind.MICROPHONE, RoutingKind.BIDIRECTIONAL, OutputKind.SPOKEN, call_bridge=True
)
# CAP-0177 Meeting (meeting contract.md §6): requirement row 8.
MEETING_MODE = UsageMode(
    InputKind.MICROPHONE, RoutingKind.BIDIRECTIONAL, OutputKind.SPOKEN, meeting=True
)


@dataclass(frozen=True, slots=True)
class SessionPair:
    """The language pair and usage mode locked for one session."""

    pair: LanguagePair
    mode: UsageMode
    fixed_source: LanguageId | None = None  # required iff routing is FIXED
    local_language: LanguageId | None = None  # Call Bridge or Meeting only

    def __post_init__(self) -> None:
        mode = self.mode
        if mode.input is InputKind.TYPED and mode.routing is RoutingKind.BIDIRECTIONAL:
            raise UnsupportedModeError("Typed input cannot use bidirectional routing")
        if mode.routing is RoutingKind.FIXED:
            if self.fixed_source is None:
                raise UnsupportedModeError("Fixed routing requires a fixed source language")
            if self.fixed_source not in self.pair:
                raise UnsupportedModeError(
                    f"Fixed source {self.fixed_source!r} is not a member of the pair"
                )
        elif self.fixed_source is not None:
            raise UnsupportedModeError("A fixed source is only valid with fixed routing")
        if mode.call_bridge or mode.meeting:
            if self.local_language is None or self.local_language not in self.pair:
                name = "Call Bridge" if mode.call_bridge else "Meeting"
                raise UnsupportedModeError(f"{name} requires a local language from the pair")
        elif self.local_language is not None:
            raise UnsupportedModeError(
                "A local language is only valid for the Call Bridge or a Meeting"
            )

    @property
    def fixed_target(self) -> LanguageId | None:
        return None if self.fixed_source is None else self.pair.other(self.fixed_source)
