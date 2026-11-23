"""English UI strings of per-language voice output (CAP-0167 contract.md §9).

Re-exported by ``lianiq.ui.strings`` (the ``strings_meeting`` precedent). ``{language}`` is
always ``LanguageRegistry.display_name`` of a language ID and ``{direction}`` the
``ROUTING_FIXED`` text of the current fixed direction: no string here names a language.
``VOICE_NAME_SPEAKER`` is defined by the Qt-free ``voice_status`` core and re-exported here.
Accessible names equal the visible label except for the ``*_NAME`` patterns below. Qt-free.
"""

from __future__ import annotations

from lianiq.conversation.voice_status import VOICE_NAME_SPEAKER  # noqa: F401 - re-export

VOICE_SECTION = "Voice output"
VOICE_SWITCH_NAME = "Speak {language}"
VOICE_READY = "{voice} · Ready"
VOICE_STATE_MISSING = "Voice missing"
VOICE_INVALID = "Voice files invalid"
VOICE_NOT_OUTPUT = "Not an output language in {direction}"
VOICE_OPTIONS = "Voice options…"
VOICE_OPTIONS_TITLE = "Voice options — {language}"
VOICE_CHOICE = "Voice"
VOICE_SPEAKER = "Speaker {number}"
VOICE_RATE = "Rate"
VOICE_RATE_VALUE = "{value:.2f}×"
VOICE_VOLUME = "Volume"
VOICE_VOLUME_VALUE = "{value} %"
VOICE_LOADING = "Loading voice…"
VOICE_CLOSE = "Close"
VOICE_REPLAY = "Replay"
VOICE_REPLAY_EMPTY = "Nothing to replay yet"
VOICE_STOP_PLAYBACK = "Stop playback"
VOICE_MIC_PAUSED = "Microphone paused while the translation is spoken"
VOICE_SYNTH_FAILED = "Could not speak the translation ({language})"
VOICE_SYNTH_FAILED_DETAIL = "The translation is shown as text. Later turns are spoken again."
VOICE_SYNTH_CONTINUES = "Recording continues."
VOICE_LOCKED_SESSION = (
    "Stop {mode} to change this voice. The running {mode} keeps its voice settings."
)
VOICE_REQUIREMENTS_HINT = (
    "Call Bridge always speaks both languages and needs both voices. "
    "Meeting dual-mic needs the voice of the table language."
)
VOICE_READINESS_ROW = "Voice {language}"

# Accessible names that differ from the visible label (contract.md §9).
VOICE_STATE_NAME = "{language} voice: {state}"
VOICE_PACKS_NAME = "Open Language packs for {language}"
VOICE_OPTIONS_NAME = "Voice options for {language}"

__all__ = [name for name in dir() if name.isupper()]
