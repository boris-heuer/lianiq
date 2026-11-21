"""Notices of the Text translation workspace (CAP-0172 contract.md §1, spec §2.2.2).

Qt-free like ``notice_catalog``. ``reason`` is always a ``TEXT_REASON_*`` text, never an
exception message or user text. A model-load failure uses the shared ``model_failed``.
"""

from __future__ import annotations

from collections.abc import Callable

from lianiq.ui import notice_catalog as catalog
from lianiq.ui import strings
from lianiq.ui.notice_catalog_base import (
    PLAYBACK_FAILED,
    TEXT_TRANSLATION,
    TRANSLATION_FAILED,
    _notice,
    busy_key,
    model_failed_key,
    retry,
)
from lianiq.ui.notices import Notice, NoticeAction, Severity

TEXT_FAILURE_KEYS = (TRANSLATION_FAILED, model_failed_key(TEXT_TRANSLATION))
PLAYBACK_KEYS = (PLAYBACK_FAILED, busy_key(TEXT_TRANSLATION))


def translation_failed(reason: str, where: str, on_retry: Callable[[], None]) -> Notice:
    return _notice(
        TRANSLATION_FAILED,
        Severity.WARNING,
        strings.TEXT_FAILED.format(reason=reason),
        strings.DETAIL_ERROR,
        where,
        strings.CONTINUES_NOTHING,
        TEXT_TRANSLATION,
        (retry(on_retry),),
    )


def model_failed(reason: str, where: str, on_retry: Callable[[], None]) -> Notice:
    return catalog.model_failed(TEXT_TRANSLATION, reason, where, on_retry)


def playback_failed(reason: str, where: str, open_audio: Callable[[], None]) -> Notice:
    """The texts stay; the session is idle again (AC-29). **Open Language packs**: WI-05."""
    return _notice(
        PLAYBACK_FAILED,
        Severity.WARNING,
        strings.TEXT_PLAYBACK_FAILED.format(reason=reason),
        strings.DETAIL_DEVICE,
        where,
        strings.CONTINUES_NOTHING,
        TEXT_TRANSLATION,
        (NoticeAction(strings.TEXT_OPEN_AUDIO, open_audio),),
    )
