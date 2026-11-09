"""Notice keys and the shared builders of ``notice_catalog`` (CAP-0168 file-size split)."""

from __future__ import annotations

from collections.abc import Callable

from lianiq.ui import strings
from lianiq.ui.notices import Notice, NoticeAction
from lianiq.ui.shell.workspaces import WorkspaceId, label

CONVERSATION = WorkspaceId.CONVERSATION
CALL_BRIDGE = WorkspaceId.CALL_BRIDGE

PAIR_LOCKED = "conversation.pair-locked"
DIRECTION_UNAVAILABLE = "conversation.direction-unavailable"
HELD_DISCARDED = "conversation.held-discarded"
QUEUE_OVERFLOW = "conversation.queue-overflow"
TURNS_DROPPED = "conversation.turns-dropped"
VOICE_MISSING = "conversation.voice-missing"
MICROPHONE_LOST = "device.microphone-lost"
SPEAKERS_LOST = "device.speakers-lost"
NO_SIGNAL = "device.no-signal"
DEVICES_CHANGED = "device.changed"
BRIDGE_DROPPED = "call-bridge.dropped"
BRIDGE_CAPTURE = "call-bridge.capture-muted"
BRIDGE_RECOVERY = "call-bridge.recovery-failed"


def unavailable_key(mode: WorkspaceId) -> str:
    return f"{mode.value}.unavailable"


def model_failed_key(mode: WorkspaceId) -> str:
    return f"{mode.value}.model-failed"


def start_failed_key(mode: WorkspaceId) -> str:
    return f"{mode.value}.start-failed"


def busy_key(mode: WorkspaceId) -> str:
    return f"{mode.value}.busy"


def error_key(workspace: WorkspaceId) -> str:
    return f"{workspace.value}.error"


def export_failed_key(workspace: WorkspaceId) -> str:
    return f"{workspace.value}.export-failed"


def export_result_key(workspace: WorkspaceId) -> str:
    return f"{workspace.value}.export-result"


def device_unavailable_key(flow: str) -> str:
    return f"device.{flow.lower()}-unavailable"


def bridge_failed_key(lane: str | None) -> str:
    return f"call-bridge.{lane or 'bridge'}-failed"


def source(mode: WorkspaceId, *parts: str | None) -> str:
    """The mode, then the known parts: "Conversation · German ↔ Mandarin (Simplified)"."""
    return strings.NOTICE_SOURCE_PART.join([label(mode), *(part for part in parts if part)])


def retry(callback: Callable[[], None]) -> NoticeAction:
    """**Retry** runs the same gate as **Start** (AC-25)."""
    return NoticeAction(strings.NOTICE_RETRY, callback)


def _notice(key, severity, title, detail, where, continues, workspace, actions=(), generation=None):
    return Notice(
        key=key,
        severity=severity,
        title=title,
        detail=detail,
        source=where,
        continues=continues,
        workspace=workspace,
        actions=tuple(actions),
        generation=generation,
    )
