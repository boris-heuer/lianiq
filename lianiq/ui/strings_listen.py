"""English UI strings of the Listen & translate workspace (CAP-0170 contract.md §9).

Re-exported through ``lianiq.ui.strings`` (the ``strings_text`` precedent). ``{reason}`` is
always one of the ``LISTEN_REASON_*`` texts, never an exception message.
"""

from __future__ import annotations

LISTEN_SOURCE_LANGUAGE = "Source language"
LISTEN_TARGET_LANGUAGE = "Target language"
LISTEN_MICROPHONE = "Microphone"
LISTEN_SWAP = "Swap languages"
LISTEN_START = "Start listening (F8)"
LISTEN_STATE_READY = "Ready"
LISTEN_STATE_LOADING = "Loading models…"
LISTEN_STATE_LISTENING = "Listening…"
LISTEN_STATE_PROCESSING = "Processing…"
LISTEN_STATE_STOPPING = "Stopping…"
LISTEN_STATE_STOPPED = "Stopped"
LISTEN_STATE_MODEL_ERROR = "Model error"
LISTEN_EMPTY = (
    "Press Start listening (F8). Each completed sentence appears here with its translation."
)
LISTEN_WAITING = "Listening — nothing heard yet."
LISTEN_RECOGNIZING = "Recognizing…"
LISTEN_TRANSLATING = "Translating…"
LISTEN_NOT_UNDERSTOOD = "Not understood"
LISTEN_SEGMENT_FAILED = "Not translated: {reason}"
LISTEN_SKIPPED = "Skipped — too much speech at once"
LISTEN_NOT_FINISHED = "Not translated before Stop"
LISTEN_NEW_BELOW = "New segments below"
LISTEN_JUMP = "Jump to latest"
LISTEN_UNSUPPORTED = "Listening in {source} with translation to {target} is not supported."
LISTEN_NO_PACK_HINT = (
    "Listen & translate needs speech recognition and a translation pack. "
    "Install them in Language packs."
)
LISTEN_MIC_MISSING = (
    "Listen & translate needs a microphone. Choose one here or in Settings › Audio devices."
)
LISTEN_LOCKED = "Stop listening to change languages or the microphone."
LISTEN_MIC_LOST = (
    "The microphone {device} is no longer available. Listening stopped; your text is kept."
)
LISTEN_OVERLOAD = "Speech arrived faster than it could be translated; some segments were skipped."
LISTEN_FAILED = "A segment could not be translated: {reason}"
LISTEN_COPY = "Copy transcript"
LISTEN_EXPORT = "Export transcript"
LISTEN_COPIED = "Copied"
LISTEN_TRANSCRIPT = "Transcript"
LISTEN_REASON_MODEL = "the model could not be used"
LISTEN_REASON_MEMORY = "not enough memory"
LISTEN_REASON_OTHER = "unexpected error (details in Diagnostics)"

__all__ = [name for name in dir() if name.startswith("LISTEN_")]
