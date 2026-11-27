"""Session-state vocabulary of every mode (session-status-truthfulness spec §2.3-§2.4).

Qt-free English strings shared by the shell and the modes; this module is their only home.
The ``STATE_*`` names avoid the existing ``strings.SESSION_STOPPING`` ("{mode} stopping…"),
which the strip keeps unchanged. ``{n}`` takes the singular form for 1 (``turns``/``contributions``).
"""

from __future__ import annotations

STATE_STOPPING = "Stopping…"
STATE_STOPPING_TURNS = "Stopping — finishing {n} turns…"
STATE_STOPPED = "Stopped · {n} turns kept"
STATE_STOPPED_LOSS = "Stopped — {n} not finished"
STATE_ERROR = "Error — see notice"
SESSION_STILL_FINISHING = (
    "Lianiq is still finishing the stopped {mode} session. Try again in a moment."
)
SESSION_STOP_TIMEOUT = (
    "{mode} stopped, but {n} turns were not finished in time. Say them again after Start."
)
SESSION_STOP_FAILED = "{mode} did not stop cleanly. Restart Lianiq if Start fails."
F8_NO_SESSION_PAGE = (
    "F8 starts a session on the Conversation, Listen & translate, Meeting or Call Bridge page."
)
NOT_TRANSLATED_STOPPED = "Not translated — stopped before it was finished."
MEETING_ENDED = "Meeting ended · {n} contributions"
MEETING_START_FAILED_STATE = "Could not start — see notice"
LISTEN_STOPPED_MIC_LOST = "Stopped — microphone lost"
LANE_DID_NOT_STOP = "Did not stop in time"
DETAIL_TURNS_DROPPED = "Say the sentence again. Lianiq keeps no audio."

# The status-bar duration of ``F8_NO_SESSION_PAGE`` (spec §2.2.1 step 2).
F8_HINT_MS = 4000


def counted(text: str, n: int) -> str:
    """``text`` with ``{n}``; "turns"/"contributions" become singular for 1 (spec §2.4)."""
    if n == 1:
        text = text.replace("{n} turns", "{n} turn").replace(
            "{n} contributions", "{n} contribution"
        )
    return text.format(n=n)


__all__ = [
    "DETAIL_TURNS_DROPPED",
    "F8_HINT_MS",
    "F8_NO_SESSION_PAGE",
    "LANE_DID_NOT_STOP",
    "LISTEN_STOPPED_MIC_LOST",
    "MEETING_ENDED",
    "MEETING_START_FAILED_STATE",
    "NOT_TRANSLATED_STOPPED",
    "SESSION_STILL_FINISHING",
    "SESSION_STOP_FAILED",
    "SESSION_STOP_TIMEOUT",
    "STATE_ERROR",
    "STATE_STOPPED",
    "STATE_STOPPED_LOSS",
    "STATE_STOPPING",
    "STATE_STOPPING_TURNS",
    "counted",
]
