"""English UI strings (CAP-0169 contract.md §2.4, CAP-0168 contract.md §6).

Lianiq has no localisation layer; these constants are the English defaults. The
missing-requirement texts are shared with ``lianiq.languages.requirements.describe``.
This module is Qt-free: the shell's Qt-free modules read their labels from it.
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

# CAP-0168 contract.md §6: shell navigation, session strip and the transcript (WI-02).
NAV_CONVERSATION = "Conversation"
NAV_TEXT_TRANSLATION = "Text translation"
NAV_LISTEN = "Listen & translate"
NAV_CALL_BRIDGE = "Call Bridge"
NAV_LANGUAGE_PACKS = "Language packs"
NAV_SETTINGS = "Settings"
NAV_PLANNED = "Planned"
NAV_PLANNED_DESCRIPTION = "Planned — not available yet"
NAV_EXPERIMENTAL = "Experimental"
SESSION_RUNNING = "{mode} running"
SESSION_STARTING = "{mode} starting…"
SESSION_STOPPING = "{mode} stopping…"
SESSION_BUSY = "Stop the {mode} session first"
STOP_ACTION = "Stop (F9)"
DIAG_TITLE = "Diagnostics"
TRANSCRIPT_EMPTY = "Press Start, then speak …"

# Not in the §6 table: composed shell labels that follow the same conventions.
NAV_REGION = "Workspaces"
# The badge sits on its own line under the label, so the 200 px sidebar never clips it.
NAV_ENTRY_BADGE = "{label}\n{badge}"
NAV_SESSION_MARKER = "●"
NAV_SESSION_ACTIVE = "Session running"
SESSION_STRIP_NAME = "Active session"
VOICE_OUTPUT = "Voice output"
SETTINGS_VOICE_OUTPUT_HINT = "The same setting as Voice output in Conversation."
DIAG_MODEL_PROFILE = "Model profile"
DIAG_COMPUTE_DEVICE = "Compute device"
DIAG_MODEL_PROFILE_BALANCED = "Balanced · Whisper small + MarianMT"
DIAG_COMPUTE_VALUE = "Speech recognition: {recognition} · Translation: {translation}"
DIAG_READINESS = "Readiness"
DIAG_READINESS_ROW = "{item}: {status}"
DIAG_READY = "Ready"

__all__ = [
    "DIAG_COMPUTE_DEVICE",
    "DIAG_COMPUTE_VALUE",
    "DIAG_MODEL_PROFILE",
    "DIAG_MODEL_PROFILE_BALANCED",
    "DIAG_READINESS",
    "DIAG_READINESS_ROW",
    "DIAG_READY",
    "DIAG_TITLE",
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
    "NAV_CALL_BRIDGE",
    "NAV_CONVERSATION",
    "NAV_ENTRY_BADGE",
    "NAV_EXPERIMENTAL",
    "NAV_LANGUAGE_PACKS",
    "NAV_LISTEN",
    "NAV_PLANNED",
    "NAV_PLANNED_DESCRIPTION",
    "NAV_REGION",
    "NAV_SESSION_ACTIVE",
    "NAV_SESSION_MARKER",
    "NAV_SETTINGS",
    "NAV_TEXT_TRANSLATION",
    "NO_PAIR_READY",
    "PAIR_LABEL",
    "PAIR_NAME",
    "PAIR_NONE_READY",
    "PAIR_PLANNED_SUFFIX",
    "ROUTING_AUTOMATIC",
    "ROUTING_FIXED",
    "SESSION_BUSY",
    "SESSION_RUNNING",
    "SESSION_STARTING",
    "SESSION_STOPPING",
    "SESSION_STRIP_NAME",
    "SETTINGS_VOICE_OUTPUT_HINT",
    "STOP_ACTION",
    "TRANSCRIPT_EMPTY",
    "VOICE_OUTPUT",
    "WINDOW_TITLE",
]
