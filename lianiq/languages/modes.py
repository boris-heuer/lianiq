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

    def __post_init__(self) -> None:
        if self.call_bridge and (
            self.input is not InputKind.MICROPHONE
            or self.routing is not RoutingKind.BIDIRECTIONAL
            or self.output is not OutputKind.SPOKEN
        ):
            raise UnsupportedModeError("Call Bridge implies microphone, bidirectional, spoken")


CALL_BRIDGE_MODE = UsageMode(
    InputKind.MICROPHONE, RoutingKind.BIDIRECTIONAL, OutputKind.SPOKEN, call_bridge=True
)


@dataclass(frozen=True, slots=True)
class SessionPair:
    """The language pair and usage mode locked for one session."""

    pair: LanguagePair
    mode: UsageMode
    fixed_source: LanguageId | None = None  # required iff routing is FIXED
    local_language: LanguageId | None = None  # Call Bridge only

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
        if mode.call_bridge:
            if self.local_language is None or self.local_language not in self.pair:
                raise UnsupportedModeError("Call Bridge requires a local language from the pair")
        elif self.local_language is not None:
            raise UnsupportedModeError("A local language is only valid for the Call Bridge")

    @property
    def fixed_target(self) -> LanguageId | None:
        return None if self.fixed_source is None else self.pair.other(self.fixed_source)
