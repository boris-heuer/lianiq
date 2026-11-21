"""Notices of the Text translation workspace (CAP-0172 contract.md §1, spec §2.2.2).

Qt-free like ``notice_catalog``. ``reason`` is always a ``TEXT_REASON_*`` text, never an
exception message or user text. A model-load failure uses the shared ``model_failed``.
"""

from __future__ import annotations

from collections.abc import Callable

from lianiq.ui import notice_catalog as catalog
from lianiq.ui import strings
from lianiq.ui.notice_catalog_base import (
    TEXT_TRANSLATION,
    TRANSLATION_FAILED,
    _notice,
    model_failed_key,
    retry,
)
from lianiq.ui.notices import Notice, Severity

TEXT_FAILURE_KEYS = (TRANSLATION_FAILED, model_failed_key(TEXT_TRANSLATION))


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
