"""One notice per mapped failure (CAP-0168 spec §2.3.4, contract.md §3 and §6).

Qt-free builders, so every mapped case is unit-testable without a display (AC-24): each
names what failed (``title``), the affected mode, lane and language (``source``), whether
recording and playback continue (``continues``) and its action — or states in ``detail``
that no action is needed. Keys are stable: a repeat of the same failure updates one notice.

| Case (§2.3.4) | Key | Severity | Action |
|---|---|---|---|
| mode/pair unavailable (``ModeUnavailableError``) | ``<mode>.unavailable`` | blocking | Retry |
| pair locked (``PairLockedError``) | ``conversation.pair-locked`` | info | none (Stop) |
| direction unavailable (Switch direction) | ``conversation.direction-unavailable`` | info | none |
| model preparation failed | ``<mode>.model-failed`` | blocking | Retry |
| start failed (device or setup error) | ``<mode>.start-failed`` | blocking | Retry |
| held turns discarded on Stop | ``conversation.held-discarded`` | warning | none |
| queue overload / dropped turns | ``conversation.queue-overflow`` / ``.turns-dropped`` | warning | none |
| missing voice | ``conversation.voice-missing`` | warning | none (provision) |
| session busy | ``<mode>.busy`` | info | none (Stop) |
| microphone / speakers lost | ``device.microphone-lost`` / ``device.speakers-lost`` | blocking | Reconnect, Choose device |
| saved device unavailable / unusable | ``device.<flow>-unavailable`` | blocking | Choose device |
| no signal / devices changed | ``device.no-signal`` / ``device.changed`` | warning / info | Choose device / none |
| export failed | ``<workspace>.export-failed`` | warning | Retry |
| Call Bridge ``BridgeEvent`` error / drop | ``call-bridge.<lane>-failed`` / ``call-bridge.dropped`` | warning / info | none (Stop) |
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from lianiq.ui import strings
from lianiq.ui.notices import Notice, NoticeAction, Severity
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


# Session start and model preparation -------------------------------------------------------


def mode_unavailable(mode: WorkspaceId, title: str, where: str, on_retry) -> Notice:
    """``title`` is ``MODE_UNAVAILABLE`` naming every missing item."""
    return _notice(
        unavailable_key(mode),
        Severity.BLOCKING,
        title,
        strings.DETAIL_RETRY,
        where,
        strings.CONTINUES_NOT_STARTED,
        mode,
        (retry(on_retry),),
    )


def pair_locked(where: str) -> Notice:
    return _notice(
        PAIR_LOCKED,
        Severity.INFO,
        strings.LOCKED_TOOLTIP,
        strings.DETAIL_LOCKED,
        where,
        strings.CONTINUES_RECORDING,
        CONVERSATION,
    )


def direction_unavailable(title: str, where: str) -> Notice:
    """**Switch direction** refused: ``title`` is ``MODE_UNAVAILABLE`` for that direction."""
    return _notice(
        DIRECTION_UNAVAILABLE,
        Severity.INFO,
        title,
        strings.DETAIL_DIRECTION,
        where,
        strings.CONTINUES_NOTHING,
        CONVERSATION,
    )


def model_failed(mode: WorkspaceId, reason: str, where: str, on_retry) -> Notice:
    return _notice(
        model_failed_key(mode),
        Severity.BLOCKING,
        strings.NOTICE_MODEL_FAILED.format(reason=reason),
        strings.DETAIL_MODEL_RETRY,
        where,
        strings.CONTINUES_NOT_STARTED,
        mode,
        (retry(on_retry),),
    )


def start_failed(mode: WorkspaceId, reason: str, where: str, on_retry) -> Notice:
    return _notice(
        start_failed_key(mode),
        Severity.BLOCKING,
        strings.NOTICE_START_FAILED.format(mode=label(mode), reason=reason),
        strings.DETAIL_START_RETRY,
        where,
        strings.CONTINUES_NOT_STARTED,
        mode,
        (retry(on_retry),),
    )


def session_busy(mode: WorkspaceId, active: WorkspaceId) -> Notice:
    """A refused start while ``active`` holds the session (spec §2.2.1 step 4)."""
    return _notice(
        busy_key(mode),
        Severity.INFO,
        strings.SESSION_BUSY.format(mode=label(active)),
        strings.DETAIL_BUSY,
        source(mode),
        strings.CONTINUES_SESSION.format(mode=label(active)),
        mode,
    )


def error(workspace: WorkspaceId, message: str, where: str | None = None) -> Notice:
    """Any other reported failure: one warning per workspace, updated on repeat."""
    return _notice(
        error_key(workspace),
        Severity.WARNING,
        message,
        strings.DETAIL_ERROR,
        where or source(workspace),
        strings.CONTINUES_NOTHING,
        workspace,
    )


# Conversation turns (``pipeline.py`` notice events) ---------------------------------------


def held_discarded(count: int, where: str) -> Notice:
    return _notice(
        HELD_DISCARDED,
        Severity.WARNING,
        strings.NOTICE_HELD_DISCARDED.format(count=count),
        strings.DETAIL_HELD,
        where,
        strings.CONTINUES_STOPPED,
        CONVERSATION,
    )


def queue_overflow(where: str, generation: int | None = None) -> Notice:
    return _notice(
        QUEUE_OVERFLOW,
        Severity.WARNING,
        strings.NOTICE_QUEUE_OVERFLOW,
        strings.DETAIL_OVERFLOW,
        where,
        strings.CONTINUES_RECORDING,
        CONVERSATION,
        generation=generation,
    )


def turns_dropped(count: int, where: str, generation: int | None = None) -> Notice:
    return _notice(
        TURNS_DROPPED,
        Severity.WARNING,
        strings.NOTICE_TURNS_DROPPED.format(count=count),
        strings.DETAIL_NONE,
        where,
        strings.CONTINUES_STOPPED,
        CONVERSATION,
        generation=generation,
    )


def voice_missing(title: str, where: str) -> Notice:
    """``title`` is ``MODE_UNAVAILABLE`` naming the missing voice."""
    return _notice(
        VOICE_MISSING,
        Severity.WARNING,
        title,
        strings.DETAIL_VOICE,
        where,
        strings.CONTINUES_TEXT_ONLY,
        CONVERSATION,
    )


# Devices (``DEVICE_*``; WI-04 wires the real detection) ------------------------------------


def _device_actions(on_reconnect, can_reconnect, on_choose) -> tuple[NoticeAction, ...]:
    actions = []
    if on_reconnect is not None:
        actions.append(
            NoticeAction(
                strings.DEVICE_RECONNECT,
                on_reconnect,
                enabled=can_reconnect,
                disabled_hint=strings.DEVICE_RECONNECT_AFTER_STOP,
            )
        )
    actions.append(NoticeAction(strings.DEVICE_CHOOSE, on_choose))
    return tuple(actions)


def microphone_lost(
    name: str, where: str, on_reconnect, can_reconnect, on_choose, generation=None
) -> Notice:
    return _notice(
        MICROPHONE_LOST,
        Severity.BLOCKING,
        strings.DEVICE_MIC_LOST.format(name=name),
        strings.DETAIL_DEVICE,
        where,
        strings.CONTINUES_MIC_LOST,
        CONVERSATION,
        _device_actions(on_reconnect, can_reconnect, on_choose),
        generation,
    )


def speakers_lost(
    name: str, where: str, on_reconnect, can_reconnect, on_choose, generation=None
) -> Notice:
    return _notice(
        SPEAKERS_LOST,
        Severity.BLOCKING,
        strings.DEVICE_SPEAKER_LOST.format(name=name),
        strings.DETAIL_DEVICE,
        where,
        strings.CONTINUES_SPEAKERS_LOST,
        CONVERSATION,
        _device_actions(on_reconnect, can_reconnect, on_choose),
        generation,
    )


def device_unavailable(
    flow: str, name: str, where: str, on_choose, reason: str | None = None
) -> Notice:
    """A saved device that is missing (``reason`` ``None``) or present but unusable."""
    title = (
        strings.DEVICE_UNAVAILABLE.format(name=name)
        if reason is None
        else strings.DEVICE_UNUSABLE.format(name=name, reason=reason)
    )
    return _notice(
        device_unavailable_key(flow),
        Severity.BLOCKING,
        title,
        strings.DETAIL_DEVICE,
        where,
        strings.CONTINUES_NOT_STARTED,
        CONVERSATION,
        _device_actions(None, None, on_choose),
    )


def no_signal(name: str, where: str, on_choose) -> Notice:
    return _notice(
        NO_SIGNAL,
        Severity.WARNING,
        strings.DEVICE_NO_SIGNAL.format(name=name),
        strings.DETAIL_DEVICE,
        where,
        strings.CONTINUES_RECORDING,
        CONVERSATION,
        _device_actions(None, None, on_choose),
    )


def devices_changed(summary: str, where: str) -> Notice:
    return _notice(
        DEVICES_CHANGED,
        Severity.INFO,
        strings.DEVICE_CHANGED.format(summary=summary),
        strings.DETAIL_NONE,
        where,
        strings.CONTINUES_RECORDING,
        CONVERSATION,
    )


# Exports -----------------------------------------------------------------------------------


def export_failed(workspace: WorkspaceId, reason: str, where: str, on_retry) -> Notice:
    """``reason`` must already be redacted (contract §6 ``EXPORT_FAILED``)."""
    return _notice(
        export_failed_key(workspace),
        Severity.WARNING,
        strings.EXPORT_FAILED.format(reason=reason),
        strings.DETAIL_EXPORT,
        where,
        strings.CONTINUES_NOTHING,
        workspace,
        (retry(on_retry),),
    )


def export_result(workspace: WorkspaceId, title: str, where: str) -> Notice:
    """Info after Copy, a saved export or a cancelled dialog."""
    return _notice(
        export_result_key(workspace),
        Severity.INFO,
        title,
        strings.DETAIL_NONE,
        where,
        strings.CONTINUES_NOTHING,
        workspace,
    )


# Call Bridge (``BridgeEvent``; event content owned by CAP-0166) ---------------------------


def bridge_failed(lane: str | None, category: str, where: str) -> Notice:
    return _notice(
        bridge_failed_key(lane),
        Severity.WARNING,
        strings.NOTICE_BRIDGE_FAILED.format(lane=lane or "", category=category).replace("  ", " "),
        strings.DETAIL_BRIDGE,
        where,
        strings.CONTINUES_LANE,
        CALL_BRIDGE,
    )


def bridge_dropped(category: str, where: str) -> Notice:
    return _notice(
        BRIDGE_DROPPED,
        Severity.INFO,
        strings.NOTICE_BRIDGE_DROPPED.format(category=category),
        strings.DETAIL_NONE,
        where,
        strings.CONTINUES_RECORDING,
        CALL_BRIDGE,
    )


def bridge_capture_muted(reason: str, where: str) -> Notice:
    return _notice(
        BRIDGE_CAPTURE,
        Severity.WARNING,
        strings.NOTICE_BRIDGE_CAPTURE.format(reason=reason),
        strings.DETAIL_BRIDGE,
        where,
        strings.CONTINUES_LANE,
        CALL_BRIDGE,
    )


def bridge_recovery_failed(reason: str, where: str) -> Notice:
    return _notice(
        BRIDGE_RECOVERY,
        Severity.WARNING,
        strings.NOTICE_BRIDGE_RECOVERY.format(reason=reason),
        strings.DETAIL_BRIDGE,
        where,
        strings.CONTINUES_RECORDING,
        CALL_BRIDGE,
    )


def keys_resolved_by_start(mode: WorkspaceId) -> Sequence[str]:
    """The notices a running session of ``mode`` resolves: their condition is gone."""
    keys = [unavailable_key(mode), model_failed_key(mode), start_failed_key(mode), busy_key(mode)]
    if mode is CONVERSATION:
        keys += [
            DIRECTION_UNAVAILABLE,
            HELD_DISCARDED,
            QUEUE_OVERFLOW,
            TURNS_DROPPED,
            MICROPHONE_LOST,
            device_unavailable_key(strings.NOTICE_MICROPHONE),
        ]
    else:
        keys += [bridge_failed_key(None), BRIDGE_DROPPED, BRIDGE_CAPTURE, BRIDGE_RECOVERY]
        keys += [bridge_failed_key(lane) for lane in ("outbound", "inbound")]
    return keys
