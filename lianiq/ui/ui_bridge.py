"""The signal hand-off from worker threads to the GUI thread (moved from ``main_window``).

``lianiq.ui.main_window.UiBridge`` stays importable through a re-export. Every Conversation
signal carries the generation of the session that produced it (session-status-truthfulness
§2.2.2); the workspace drops the signals of another generation.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal


class UiBridge(QObject):
    result = Signal(object, int)  # TranslationResult, session generation
    held = Signal(object, int)  # HeldTurn, session generation
    held_resolved = Signal(int)  # session generation
    error = Signal(str, int)  # message, session generation
    busy = Signal(bool, int)  # busy, session generation
    level = Signal(float)
    session_ready = Signal(int, bool, str)  # start generation, ready, error message
    call_bridge_ready = Signal(int, bool, str)
    call_bridge_event = Signal(object)
    call_bridge_result = Signal(int, object)  # start generation, TranslationResult
    call_bridge_stopped = Signal(int, object)  # start generation, LaneStopResult
    call_bridge_level = Signal(object, float)
    call_bridge_capture_fault = Signal(object, str)
    pipeline_event = Signal(object, int)  # PipelineEvent, session generation
    packs_event = Signal(object)  # CAP-0171 pack jobs
    playback_state = Signal(str, int)  # CAP-0167 ``PlaybackState`` value, session generation
    conversation_stopped = Signal(int, object)  # generation, StopReport or the stop's error
