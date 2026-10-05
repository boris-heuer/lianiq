from __future__ import annotations

import pytest

from offline_translator.domain import Language
from offline_translator.stt.faster_whisper_engine import _normalize_language


def test_normalize_supported_languages() -> None:
    assert _normalize_language("de") is Language.GERMAN
    assert _normalize_language("zh") is Language.MANDARIN
    assert _normalize_language("cmn") is Language.MANDARIN


def test_reject_unsupported_language() -> None:
    with pytest.raises(ValueError):
        _normalize_language("en")
