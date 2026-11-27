"""The signal hand-off from worker threads to the GUI thread (moved from ``main_window``).

``lianiq.ui.main_window.UiBridge`` stays importable through a re-export.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal


class UiBridge(QObject):
    result = Signal(object, int)  # TranslationResult, owner generation at emit
    held = Signal(object)
    held_resolved = Signal()
    error = Signal(str)
    busy = Signal(bool)
    level = Signal(float)
    session_ready = Signal(int, bool, str)  # start generation, ready, error message
    call_bridge_ready = Signal(int, bool, str)
    call_bridge_event = Signal(object)
    call_bridge_result = Signal(object)
    call_bridge_level = Signal(object, float)
    call_bridge_capture_fault = Signal(object, str)
    pipeline_event = Signal(object, int)  # PipelineEvent, session generation
    packs_event = Signal(object)  # CAP-0171 pack jobs
    playback_state = Signal(str)  # CAP-0167 ``PlaybackState`` value of spoken output
