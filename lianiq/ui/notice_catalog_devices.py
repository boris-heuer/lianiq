"""Device, export and Call Bridge notices of ``notice_catalog`` (CAP-0168 file-size split)."""

from __future__ import annotations

from lianiq.ui import strings
from lianiq.ui.notice_catalog_base import (
    BRIDGE_CAPTURE,
    BRIDGE_DROPPED,
    BRIDGE_RECOVERY,
    CALL_BRIDGE,
    CONVERSATION,
    DEVICES_CHANGED,
    MICROPHONE_LOST,
    NO_SIGNAL,
    SPEAKERS_LOST,
    _notice,
    bridge_failed_key,
    device_unavailable_key,
    export_failed_key,
    export_result_key,
    retry,
)
from lianiq.ui.notices import Notice, NoticeAction, Severity
from lianiq.ui.shell.workspaces import WorkspaceId

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


def device_migrated(flow: str, name: str, where: str) -> Notice:
    """A legacy device index became this choice (contract §7 step 3); reported once."""
    return _notice(
        f"device.{flow.lower()}-migrated",
        Severity.INFO,
        strings.DEVICE_MIGRATED.format(flow=flow, name=name),
        strings.DETAIL_NONE,
        where,
        strings.CONTINUES_NOTHING,
        CONVERSATION,
    )


def default_changed(flow: str, name: str, where: str, workspace=WorkspaceId.SETTINGS) -> Notice:
    """**Refresh** found a new Windows default for a flow that follows it (AC-16)."""
    return _notice(
        f"device.{flow.lower()}-default",
        Severity.INFO,
        strings.DEVICE_DEFAULT_NOW.format(flow=flow.lower(), name=name),
        strings.DETAIL_NONE,
        where,
        strings.CONTINUES_NOTHING,
        workspace,
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
