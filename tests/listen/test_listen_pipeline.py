"""CAP-0170 contract §4: shared adapters, no voice, own context (AC-07, AC-23, AC-24)."""

from __future__ import annotations

import pytest

from lianiq.languages.errors import UnsupportedModeError
from lianiq.listen.pipeline import ListenPipeline
from lianiq.listen.session import listen_session
from lianiq.pipeline import TranslationPipeline
from tests._pipeline_helpers import DE, PAIR, ZH, FakeRecognizer, FakeTranslator, bound


class WarmSpy:
    def __init__(self, inner) -> None:
        self.inner = inner
        self.warmed: list = []

    def warm_up(self, subjects) -> None:
        self.warmed.append(subjects)

    def __getattr__(self, name):
        return getattr(self.inner, name)


def test_listen_uses_the_shared_adapters_and_never_speaks() -> None:
    recognizer, translator = WarmSpy(FakeRecognizer()), WarmSpy(FakeTranslator())
    listen = ListenPipeline(TranslationPipeline(recognizer, translator))
    session = listen_session(PAIR, DE)
    listen.prepare(session)
    assert recognizer.warmed == [("de",)] and len(translator.warmed) == 1
    assert listen.spoken is None and not listen.voice_output
    with pytest.raises(UnsupportedModeError):
        listen.voice_synthesizer()
    result = listen.process(bound(session))
    assert (result.source_language, result.target_language) == (DE, ZH)
    assert recognizer.inner.calls == ["de"]  # forced to the fixed source


def test_listen_context_is_separate_from_the_shared_pipeline() -> None:
    shared = TranslationPipeline(FakeRecognizer(), FakeTranslator())
    listen = ListenPipeline(shared)
    listen.process(bound(listen_session(PAIR, DE)))
    assert shared.context.source_context(DE) == ()
    assert listen.context.source_context(DE) != ()
