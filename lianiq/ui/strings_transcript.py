"""English UI strings of the paired transcript view (paired-transcript spec §2.4).

Re-exported through ``lianiq.ui.strings`` (the ``strings_listen`` precedent). The Listen
names ``LISTEN_NEW_BELOW``, ``LISTEN_JUMP``, ``LISTEN_COPY``, ``LISTEN_EXPORT``,
``LISTEN_COPIED`` and ``LISTEN_TRANSCRIPT`` are aliases of these keys.
"""

from __future__ import annotations

TRANSCRIPT_LIST = "Transcript"
TRANSCRIPT_NEW_BELOW = "New turns below"
TRANSCRIPT_JUMP = "Jump to latest"
TRANSCRIPT_COPY_ORIGINAL = "Copy original"
TRANSCRIPT_COPY_TRANSLATION = "Copy translation"
TRANSCRIPT_COPY_PAIR = "Copy pair"
TRANSCRIPT_REPLAY = "Replay"
TRANSCRIPT_STOP_PLAYBACK = "Stop playback"
TRANSCRIPT_COPY_ALL = "Copy transcript"
TRANSCRIPT_EXPORT_ALL = "Export transcript"
TRANSCRIPT_COPIED = "Copied"
TRANSCRIPT_NEW_CONVERSATION = "New conversation"
TRANSCRIPT_CLEAR = "Clear transcript"
TRANSCRIPT_CLEAR_TITLE = "Clear the transcript?"
TRANSCRIPT_CLEAR_TEXT = "{count} translated turns have not been exported. They will be lost."
TRANSCRIPT_CLEAR_CONFIRM = "Clear"
TRANSCRIPT_REPLAY_NO_VOICE = "No ready voice for {language}"
TRANSCRIPT_REPLAY_NO_SPEAKERS = "Speakers unavailable"
TRANSCRIPT_SAVED = "Transcript saved: {path}"

__all__ = [name for name in dir() if name.startswith("TRANSCRIPT_")]
