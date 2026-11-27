"""English UI strings of the Call Bridge workspace (CAP-0166 spec §2.3, §3.4).

The role labels and readiness texts live Qt-free in ``lianiq/call_bridge/texts.py`` (the
readiness core names its reasons with them) and are re-exported here, not copied.
``{local}`` and ``{remote}`` are registry English language names. Qt-free.
"""

from __future__ import annotations

from lianiq.call_bridge import texts as _texts
from lianiq.call_bridge.contracts import EndpointRole

# Re-exported from the Qt-free core (the same objects, not copies).
CB_ROLE_LABELS = _texts.ROLE_LABELS
CB_R_AMBIGUOUS = _texts.R_AMBIGUOUS
CB_R_DUPLICATE = _texts.R_DUPLICATE
CB_R_MODE_UNAVAILABLE = _texts.R_MODE_UNAVAILABLE
CB_R_MODELS_WARMING = _texts.R_MODELS_WARMING
CB_R_NEEDS_CAPTURE = _texts.R_NEEDS_CAPTURE
CB_R_NEEDS_RENDER = _texts.R_NEEDS_RENDER
CB_R_NOT_FOUND = _texts.R_NOT_FOUND
CB_R_RUNNING = _texts.R_RUNNING
CB_R_SAME_CABLE = _texts.R_SAME_CABLE
CB_R_SELECT = _texts.R_SELECT

CB_EXPERIMENTAL = (
    "Experimental. A passed test checks one path; it does not certify your call setup."
)
CB_CHECKLIST_LINK = "Real-call checklist"
CB_PATH_OUT_NAME = "You → call"
CB_PATH_IN_NAME = "Call → you"
CB_PATH_OUT = CB_PATH_OUT_NAME + " · {local} → {remote}"
CB_PATH_IN = CB_PATH_IN_NAME + " · {remote} → {local}"
CB_ROLE_LOCAL_MIC = CB_ROLE_LABELS[EndpointRole.LOCAL_MICROPHONE]
CB_ROLE_CALL_MIC = CB_ROLE_LABELS[EndpointRole.CALL_MICROPHONE_RENDER]
CB_ROLE_CALL_SPEAKER = CB_ROLE_LABELS[EndpointRole.CALL_SPEAKER_CAPTURE]
CB_ROLE_HEADPHONES = CB_ROLE_LABELS[EndpointRole.LOCAL_HEADPHONES]
CB_SELECT = "Select a device …"
CB_TEST = "Test"
CB_CANCEL = "Cancel"
CB_YES = "Yes"
CB_NO = "No"
CB_Q_OUT = "Did your partner hear it?"
CB_Q_IN = "Did you hear it?"
CB_T_NOT_TESTED = "Not tested"
CB_T_PLAYING = "Playing test…"
CB_T_PASSED = "Test passed"
CB_T_FAILED = "Test failed — check the call app's {setting}"
CB_T_CANCELLED = "Test cancelled"
CB_T_PLAY_ERROR = "Test could not play: {reason}"
CB_SETTING_OUT = "microphone setting"
CB_SETTING_IN = "speaker setting"
CB_TEST_NO_PHRASE = "No test phrase for {language}"
CB_TEST_RUNNING = "Stop the call bridge to test a path"
CB_TEST_ROW = "Route test"  # accessible name prefix of the test row
CB_LANE_STOPPED = "Stopped"
CB_LANE_STARTING = "Starting…"
CB_LANE_LISTENING = "Listening"
CB_LANE_TRANSLATING = "Translating…"
CB_LANE_SPEAKING = "Speaking"
CB_LANE_ECHO_PAUSED = "Paused while you hear the translation"
CB_LANE_MUTED = "Muted — {reason}"
CB_LANE_DEVICE_LOST = "Device lost — {device}"
CB_LANE_RECONNECTING = "Reconnecting…"
CB_LANE_STATUS = "Lane status"  # accessible name prefix of the status line
CB_LEVEL_MIC = "Microphone level"
CB_LEVEL_CALL = "Call audio level"
CB_LEVEL_SIGNAL = "Signal"
CB_LEVEL_NO_SIGNAL = "No signal for 5 s — {hint}"
CB_LEVEL_CLIPPING = "Too loud (clipping)"
CB_LEVEL_CLIPPING_HINT = CB_LEVEL_CLIPPING + " — {hint}"
CB_HINT_MIC = "is the right microphone selected and unmuted?"
CB_HINT_CALL = "is the call app's speaker set to the call speaker cable?"
CB_CLIP_HINT_MIC = "lower your microphone volume"
CB_CLIP_HINT_CALL = "lower the call app's speaker volume"
CB_HELP_TITLE = "How to set up the call app"
CB_HELP_OUT = (
    "In your call app, choose the recording side of the call microphone cable as the "
    "microphone. Example: WeChat › Settings › Audio › Microphone."
)
CB_HELP_IN = (
    "In your call app, choose the playback side of the call speaker cable as the "
    "speaker. Example: WeChat › Settings › Audio › Speaker."
)
CB_READINESS = "Before you can start"  # accessible name of the readiness list
CB_TEXT_EMPTY = "Nothing translated yet."
CB_TEXT_TITLE = "Live call text"  # label and accessible name of the live text view
CB_R_TESTING = "Finish or cancel the route test first"
