"""Per-input language gate (CAP-0177 contract.md §2).

Qt-free. Each meeting input expects one pair language: the table input the table language,
the PO microphone the local language. The detection pass decides:

* ``ACCEPT`` iff the detected language is the expected one with ``probability`` at or above
  ``min_probability`` (``languages.detection_min_probability``): reuse the detection text;
* ``DISCARD`` iff it is the other pair language at or above that threshold: the contribution
  keeps no text anywhere, only the ignored counter of its input increments;
* ``FORCE_EXPECTED`` in every other case (low probability, a language outside the pair, or no
  registry language): a second pass forced to the expected language is used, even if its text
  is empty (then the contribution is dropped as silence, not counted as "other language").
"""

from __future__ import annotations

from enum import StrEnum

from lianiq.domain import Transcript
from lianiq.languages.registry import LanguageId, LanguagePair


class GateDecision(StrEnum):
    ACCEPT = "accept"  # detection = expected: reuse the detection-pass text
    DISCARD = "discard"  # other pair language with probability >= min_probability
    FORCE_EXPECTED = "force"  # otherwise: second pass forced to expected


class LanguageGate:
    def __init__(self, expected: LanguageId, pair: LanguagePair, min_probability: float) -> None:
        if not 0.0 <= min_probability <= 1.0:
            raise ValueError("min_probability must be between 0 and 1")
        self.expected = expected
        self._other = pair.other(expected)  # raises ValueError unless a pair member
        self.min_probability = min_probability

    def decide(self, detection: Transcript) -> GateDecision:
        if detection.probability >= self.min_probability:
            if detection.language == self.expected:
                return GateDecision.ACCEPT
            if detection.language == self._other:
                return GateDecision.DISCARD
        return GateDecision.FORCE_EXPECTED
