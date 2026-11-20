"""Voice controls of an engine and per-call voice options (CAP-0167 contract.md §1).

Qt-free. ``VoiceOptions()`` (all defaults) reproduces the synthesis without options exactly.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

RATE_RANGE = (0.75, 1.5)  # step 0.05 in the UI
VOLUME_RANGE = (0.1, 1.0)  # step 0.05 in the UI


@dataclass(frozen=True, slots=True)
class VoiceControls:
    """What one language's engine offers.

    ``speakers`` > 1 shows a Voice choice, 1 shows none, ``None`` means unknown until the
    voice is loaded (sherpa-onnx).
    """

    speakers: int | None
    rate: bool
    volume: bool


def _in_range(value: object, bounds: tuple[float, float]) -> bool:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return False
    return math.isfinite(value) and bounds[0] <= value <= bounds[1]


@dataclass(frozen=True, slots=True)
class VoiceOptions:
    """Applied per synthesis call; never reloads a model.

    ``speaker`` ``None`` keeps the engine's configured speaker (sherpa-onnx ``speaker_id``).
    """

    speaker: int | None = None
    rate: float = 1.0
    volume: float = 1.0

    def __post_init__(self) -> None:
        if self.speaker is not None and (type(self.speaker) is not int or self.speaker < 0):
            raise ValueError(f"voice speaker must be null or an integer >= 0: {self.speaker!r}")
        if not _in_range(self.rate, RATE_RANGE):
            raise ValueError(f"voice rate must be from {RATE_RANGE[0]} to {RATE_RANGE[1]}")
        if not _in_range(self.volume, VOLUME_RANGE):
            raise ValueError(f"voice volume must be from {VOLUME_RANGE[0]} to {VOLUME_RANGE[1]}")


def check_speaker(options: VoiceOptions, speakers: int, voice: object) -> None:
    """Raise ``ValueError`` for a chosen speaker the voice does not have."""
    if options.speaker is not None and options.speaker >= speakers:
        raise ValueError(
            f"voice speaker {options.speaker} is out of range for {voice} ({speakers} speakers)"
        )
