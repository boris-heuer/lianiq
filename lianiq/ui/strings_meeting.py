"""English UI strings of the Meeting workspace (CAP-0177 contract.md §7).

Re-exported by ``lianiq.ui.strings`` (``strings.MEETING_START`` …), which keeps the English
defaults in one namespace; this module only keeps ``strings.py`` under the file-size limit.
``{language}`` is always the registry English name of a ``LanguageId``: no string here names
a language. Qt-free.
"""

from __future__ import annotations

NAV_MEETING = "Meeting"
MEETING_TABLE_GROUP = "Table speakerphone"
MEETING_TABLE_MIC = "Table microphone"
MEETING_TABLE_SPEAKER = "Table speaker"
MEETING_USER_MIC = "Your microphone"
MEETING_YOUR_LANGUAGE = "Your language"
MEETING_TABLE_LANGUAGE = "Table language: {language}"
MEETING_SPEAK_LOCAL = "Speak {language} for me"
MEETING_LOCAL_OUTPUT = "Output for {language} speech"
MEETING_LOCAL_IS_HEADSET = "This output is a headset (no sound reaches the room)"
MEETING_TABLE_DURING_OUTPUT = "Table microphone while Lianiq speaks {language}"
MEETING_TABLE_MUTE = "Muted (recommended)"
MEETING_TABLE_OPEN = "Open — relies on the speakerphone's echo cancellation"
MEETING_OPTIONS_LOCKED = "Available when no meeting is running"
MEETING_START = "Start meeting"
MEETING_END = "End meeting"
MEETING_EMPTY = "Listening — nothing said yet"
MEETING_PENDING = "Translating…"
MEETING_LINE_TABLE = "Table"
MEETING_LINE_YOU = "You"
MEETING_LISTENING = "Listening"
MEETING_MUTED_WHILE_SPEAKING = "Muted while speaking {language}"
MEETING_DEVICE_LOST = "Device lost"
MEETING_IGNORED_COUNT = "{count} contribution(s) in another language ignored"
MEETING_FALLING_BEHIND = "Translation is falling behind — nothing is lost"
MEETING_CONFLICT_USER_IS_TABLE = "Your microphone is the table microphone"
MEETING_CONFLICT_LOCAL_IS_TABLE = "{language} speech cannot use the table speaker"
MEETING_SAVE_PROMPT = (
    "Save a text transcript in both languages on this computer? Audio is never saved."
)
MEETING_SAVE = "Save…"
MEETING_DONT_SAVE = "Don't save"
MEETING_SAVE_FAILED = "The transcript could not be saved: {reason}"

# Not in the §7 table (proposed §7 addendum): the reason of the start-failed notice when the
# window was built without the controller factory ``lianiq.app`` registers.
MEETING_NO_CONTROLLER = "No meeting controller is configured in this build"
# Not in the §7 table (proposed §7 addendum, WI-05): the title and accessible name of the
# running text view.
MEETING_RUNNING_VIEW = "Meeting text"

__all__ = [
    "MEETING_CONFLICT_LOCAL_IS_TABLE",
    "MEETING_CONFLICT_USER_IS_TABLE",
    "MEETING_DEVICE_LOST",
    "MEETING_DONT_SAVE",
    "MEETING_EMPTY",
    "MEETING_END",
    "MEETING_FALLING_BEHIND",
    "MEETING_IGNORED_COUNT",
    "MEETING_LINE_TABLE",
    "MEETING_LINE_YOU",
    "MEETING_LISTENING",
    "MEETING_LOCAL_IS_HEADSET",
    "MEETING_LOCAL_OUTPUT",
    "MEETING_MUTED_WHILE_SPEAKING",
    "MEETING_NO_CONTROLLER",
    "MEETING_OPTIONS_LOCKED",
    "MEETING_PENDING",
    "MEETING_RUNNING_VIEW",
    "MEETING_SAVE",
    "MEETING_SAVE_FAILED",
    "MEETING_SAVE_PROMPT",
    "MEETING_SPEAK_LOCAL",
    "MEETING_START",
    "MEETING_TABLE_DURING_OUTPUT",
    "MEETING_TABLE_GROUP",
    "MEETING_TABLE_LANGUAGE",
    "MEETING_TABLE_MIC",
    "MEETING_TABLE_MUTE",
    "MEETING_TABLE_OPEN",
    "MEETING_TABLE_SPEAKER",
    "MEETING_USER_MIC",
    "MEETING_YOUR_LANGUAGE",
    "NAV_MEETING",
]
