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

from collections.abc import Sequence

from lianiq.ui import strings

# CAP-0168 file-size split: keys, shared builders and the device, export and Call Bridge
# notices moved; re-exported, so every ``notice_catalog.<name>`` keeps working.
from lianiq.ui.notice_catalog_base import (
    BRIDGE_CAPTURE,
    BRIDGE_DROPPED,
    BRIDGE_RECOVERY,
    CALL_BRIDGE,  # noqa: F401 - re-export
    CONVERSATION,
    DEVICES_CHANGED,  # noqa: F401 - re-export
    DIRECTION_UNAVAILABLE,
    HELD_DISCARDED,
    MICROPHONE_LOST,
    NO_SIGNAL,  # noqa: F401 - re-export
    PAIR_LOCKED,
    QUEUE_OVERFLOW,
    SPEAKERS_LOST,  # noqa: F401 - re-export
    TURNS_DROPPED,
    VOICE_MISSING,
    _notice,
    bridge_failed_key,
    busy_key,
    device_unavailable_key,
    error_key,
    export_failed_key,  # noqa: F401 - re-export
    export_result_key,  # noqa: F401 - re-export
    model_failed_key,
    retry,
    source,
    start_failed_key,
    unavailable_key,
)
from lianiq.ui.notice_catalog_devices import (
    _device_actions,  # noqa: F401 - re-export
    bridge_capture_muted,  # noqa: F401 - re-export
    bridge_dropped,  # noqa: F401 - re-export
    bridge_failed,  # noqa: F401 - re-export
    bridge_recovery_failed,  # noqa: F401 - re-export
    default_changed,  # noqa: F401 - re-export
    device_migrated,  # noqa: F401 - re-export
    device_unavailable,  # noqa: F401 - re-export
    devices_changed,  # noqa: F401 - re-export
    export_failed,  # noqa: F401 - re-export
    export_result,  # noqa: F401 - re-export
    microphone_lost,  # noqa: F401 - re-export
    no_signal,  # noqa: F401 - re-export
    speakers_lost,  # noqa: F401 - re-export
)
from lianiq.ui.notices import Notice, Severity
from lianiq.ui.shell.workspaces import WorkspaceId, label

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
