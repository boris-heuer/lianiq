"""English UI strings of the language pair contract (CAP-0169 contract.md §2.4).

Lianiq has no localisation layer; these constants are the English defaults. The
missing-requirement texts are shared with ``lianiq.languages.requirements.describe``.
"""

from __future__ import annotations

from lianiq.languages.requirements import (
    MISSING_DEVICE,
    MISSING_RECOGNITION,
    MISSING_TRANSLATION,
    MISSING_VOICE,
)
from lianiq.languages.session import LOCKED_MESSAGE

PAIR_LABEL = "Language pair"
PAIR_PLANNED_SUFFIX = "– planned, unavailable"
PAIR_NONE_READY = "No ready language pair"
ROUTING_AUTOMATIC = "Automatic ({a} ↔ {b})"
ROUTING_FIXED = "{source} → {target}"
MODE_UNAVAILABLE = "Not available: missing {items}"
NO_PAIR_READY = "No language pair is ready. Provision languages first (Language readiness)."
HELD_TITLE = "Language unclear — choose the spoken language"
HELD_TRANSLATE_AS = "Translate as {language}"
HELD_DISCARD = "Discard"
HELD_COUNTER = "{index} of {count}"
LOCKED_TOOLTIP = LOCKED_MESSAGE

# Not in the §2.4 table: composed labels that follow the same conventions.
PAIR_NAME = "{a} ↔ {b}"
WINDOW_TITLE = "lianiq · {pair}"
HELD_DETECTED = "Detected: {language}"

__all__ = [
    "HELD_COUNTER",
    "HELD_DETECTED",
    "HELD_DISCARD",
    "HELD_TITLE",
    "HELD_TRANSLATE_AS",
    "LOCKED_TOOLTIP",
    "MISSING_DEVICE",
    "MISSING_RECOGNITION",
    "MISSING_TRANSLATION",
    "MISSING_VOICE",
    "MODE_UNAVAILABLE",
    "NO_PAIR_READY",
    "PAIR_LABEL",
    "PAIR_NAME",
    "PAIR_NONE_READY",
    "PAIR_PLANNED_SUFFIX",
    "ROUTING_AUTOMATIC",
    "ROUTING_FIXED",
    "WINDOW_TITLE",
]
