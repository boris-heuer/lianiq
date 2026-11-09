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

# CAP-0168 contract.md §6: notices, devices and diagnostics (WI-03).
DEVICE_UNAVAILABLE = "{name} — unavailable"
DEVICE_UNUSABLE = "{name} — {reason}"
DEVICE_NO_SIGNAL = "No signal from '{name}'. Check mute or choose another microphone."
DEVICE_MIC_LOST = "Microphone '{name}' disconnected. Recording stopped. Your transcript is kept."
DEVICE_SPEAKER_LOST = (
    "Speakers '{name}' disconnected. Spoken output stopped; translations still appear as text."
)
DEVICE_CHANGED = "Audio devices changed: {summary}. The running session keeps its devices."
DEVICE_RECONNECT = "Reconnect"
DEVICE_CHOOSE = "Choose device"
DEVICE_RECONNECT_AFTER_STOP = "Available after Stop"
NOTICE_MORE = "+{count} more"
NOTICE_RETRY = "Retry"
DIAG_COPY = "Copy"
DIAG_EXPORT = "Export…"
DIAG_EMPTY = "Nothing recorded yet."
EXPORT_FAILED = "Export failed: {reason}. Nothing was lost; try another folder."

# Not in the §6 table: composed notice texts that follow the same conventions.
NOTICE_REGION = "Notices"
NOTICE_INFO = "Information"
NOTICE_WARNING = "Warning"
NOTICE_BLOCKING = "Action needed"
NOTICE_DISMISS = "Dismiss"
NOTICE_ACCESSIBLE_NAME = "{severity}: {title}"
NOTICE_ACCESSIBLE_DESCRIPTION = "{source}. {continues} {detail}"
NOTICE_REPEATED = "{title} ({count}×)"
NOTICE_SOURCE_PART = " · "
NOTICE_MODEL_FAILED = "Models could not be prepared: {reason}"
NOTICE_START_FAILED = "{mode} could not start: {reason}"
NOTICE_QUEUE_OVERFLOW = "The audio queue was full; the oldest pending segment was dropped."
NOTICE_TURNS_DROPPED = (
    "{count} queued speech segment(s) were not translated before the session stopped "
    "and were dropped."
)
NOTICE_HELD_DISCARDED = "{count} turn(s) with an unclear language were discarded"
NOTICE_BRIDGE_FAILED = "Call Bridge {lane} lane failed closed: {category}"
NOTICE_BRIDGE_DROPPED = "Call Bridge dropped stale work: {category}"
NOTICE_BRIDGE_CAPTURE = "Call Bridge capture muted: {reason}"
NOTICE_BRIDGE_RECOVERY = "Endpoint recovery check failed: {reason}"
NOTICE_SPEAKERS = "Speakers"
NOTICE_MICROPHONE = "Microphone"
CONTINUES_NOT_STARTED = "Recording has not started."
CONTINUES_RECORDING = "Recording continues."
CONTINUES_STOPPED = "Recording stopped. Your transcript is kept."
CONTINUES_MIC_LOST = "Recording stopped. Playback stopped."
CONTINUES_SPEAKERS_LOST = "Recording continues. Spoken output stopped."
CONTINUES_TEXT_ONLY = "Recording continues; translations appear as text only."
CONTINUES_SESSION = "The {mode} session continues."
CONTINUES_NOTHING = "Recording and playback are not affected."
CONTINUES_LANE = "This lane is muted; the other lane continues."
DETAIL_RETRY = "Provision what is missing or choose another pair or direction, then press Retry."
DETAIL_MODEL_RETRY = "Check the model files, then press Retry."
DETAIL_START_RETRY = "Check the device and settings, then press Retry."
DETAIL_LOCKED = "Press Stop (F9) first. No other action is needed."
DETAIL_NONE = "No action needed."
DETAIL_HELD = (
    "No action needed. Next time choose the spoken language in the bar above the transcript."
)
DETAIL_OVERFLOW = "No action needed; pause briefly between turns if this repeats."
DETAIL_VOICE = "Provision the voice to hear spoken output; text output works without it."
DETAIL_DEVICE = "Reconnect the device, or choose another one."
DETAIL_DIRECTION = "The direction is unchanged. Provision what is missing to use the other one."
DETAIL_BUSY = "Press Stop (F9), then Start again."
DETAIL_BRIDGE = "Stop the Call Bridge, check its endpoints, then Start again."
DETAIL_EXPORT = "Press Retry to choose another folder."
DETAIL_ERROR = "Try again. If this repeats, export Settings › Diagnostics."
DIAG_HISTORY = "Notice history"
DIAG_EXPORT_TITLE = "Export diagnostics"
DIAG_EXPORT_FILTER = "Text (*.txt)"
DIAG_EXPORT_NAME = "lianiq-diagnostics.txt"
DIAG_EXPORT_CANCELLED = "Export cancelled. Nothing was written; the log is kept."
DIAG_EXPORT_SAVED = "Diagnostics saved as '{name}'."
DIAG_COPIED = "Diagnostics copied to the clipboard."
TRANSCRIPT_EXPORT = "Transcript export"

__all__ = [
    "CONTINUES_LANE",
    "CONTINUES_MIC_LOST",
    "CONTINUES_NOTHING",
    "CONTINUES_NOT_STARTED",
    "CONTINUES_RECORDING",
    "CONTINUES_SESSION",
    "CONTINUES_SPEAKERS_LOST",
    "CONTINUES_STOPPED",
    "CONTINUES_TEXT_ONLY",
    "DETAIL_BRIDGE",
    "DETAIL_BUSY",
    "DETAIL_DEVICE",
    "DETAIL_DIRECTION",
    "DETAIL_ERROR",
    "DETAIL_EXPORT",
    "DETAIL_HELD",
    "DETAIL_LOCKED",
    "DETAIL_MODEL_RETRY",
    "DETAIL_NONE",
    "DETAIL_OVERFLOW",
    "DETAIL_RETRY",
    "DETAIL_START_RETRY",
    "DETAIL_VOICE",
    "DEVICE_CHANGED",
    "DEVICE_CHOOSE",
    "DEVICE_MIC_LOST",
    "DEVICE_NO_SIGNAL",
    "DEVICE_RECONNECT",
    "DEVICE_RECONNECT_AFTER_STOP",
    "DEVICE_SPEAKER_LOST",
    "DEVICE_UNAVAILABLE",
    "DEVICE_UNUSABLE",
    "DIAG_COMPUTE_DEVICE",
    "DIAG_COMPUTE_VALUE",
    "DIAG_COPIED",
    "DIAG_COPY",
    "DIAG_EMPTY",
    "DIAG_EXPORT",
    "DIAG_EXPORT_CANCELLED",
    "DIAG_EXPORT_FILTER",
    "DIAG_EXPORT_NAME",
    "DIAG_EXPORT_SAVED",
    "DIAG_EXPORT_TITLE",
    "DIAG_HISTORY",
    "DIAG_MODEL_PROFILE",
    "DIAG_MODEL_PROFILE_BALANCED",
    "DIAG_READINESS",
    "DIAG_READINESS_ROW",
    "DIAG_READY",
    "DIAG_TITLE",
    "EXPORT_FAILED",
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
    "NOTICE_ACCESSIBLE_DESCRIPTION",
    "NOTICE_ACCESSIBLE_NAME",
    "NOTICE_BLOCKING",
    "NOTICE_BRIDGE_CAPTURE",
    "NOTICE_BRIDGE_DROPPED",
    "NOTICE_BRIDGE_FAILED",
    "NOTICE_BRIDGE_RECOVERY",
    "NOTICE_DISMISS",
    "NOTICE_HELD_DISCARDED",
    "NOTICE_INFO",
    "NOTICE_MICROPHONE",
    "NOTICE_MODEL_FAILED",
    "NOTICE_MORE",
    "NOTICE_QUEUE_OVERFLOW",
    "NOTICE_REGION",
    "NOTICE_REPEATED",
    "NOTICE_RETRY",
    "NOTICE_SOURCE_PART",
    "NOTICE_SPEAKERS",
    "NOTICE_START_FAILED",
    "NOTICE_TURNS_DROPPED",
    "NOTICE_WARNING",
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
    "TRANSCRIPT_EXPORT",
    "VOICE_OUTPUT",
    "WINDOW_TITLE",
]
