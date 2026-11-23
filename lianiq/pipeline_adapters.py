"""Requirement-scoped adapter construction of ``TranslationPipeline`` (from ``pipeline.py``)."""

from __future__ import annotations

import logging

from lianiq.languages.capabilities import DirectedEdge
from lianiq.languages.modes import SessionPair
from lianiq.languages.registry import LanguageId
from lianiq.languages.requirements import RequirementKind, ordered_requirements
from lianiq.pipeline_types import SpeechRecognizer, Synthesizer, Translator, _warm_up

# The ``lianiq.pipeline`` logger, as before the move.
LOGGER = logging.getLogger("lianiq.pipeline")


class PipelineAdapters:
    """``TranslationPipeline`` base: adapters are constructed on first need."""

    # Adapters are constructed on first need, never before a mode requires them.
    def speech_recognizer(self) -> SpeechRecognizer:
        with self._adapter_lock:
            if self.recognizer is None:
                self.recognizer = self._construct("recognizer")
            return self.recognizer

    def text_translator(self) -> Translator:
        with self._adapter_lock:
            if self.translator is None:
                self.translator = self._construct("translator")
            return self.translator

    def voice_synthesizer(self) -> Synthesizer:
        with self._adapter_lock:
            if self.synthesizer is None:
                self.synthesizer = self._construct("synthesizer")
            return self.synthesizer

    def drop_adapters(self, names) -> None:
        """Forget the cached adapters ``names`` (their model files changed, spec §3.4); the
        next need constructs them again. An adapter without a factory is kept."""
        with self._adapter_lock:
            for name in names:
                if getattr(self.factories, name) is not None:
                    setattr(self, name, None)

    def _construct(self, name: str):
        factory = getattr(self.factories, name)
        if factory is None:
            raise RuntimeError(f"No speech {name} adapter is configured")
        LOGGER.info("Constructing the %s adapter", name)
        return factory()

    @property
    def voice_output(self) -> bool:
        """Whether any language is spoken (read-only; ``set_spoken_languages`` changes it)."""
        return bool(self.spoken_languages)

    def prepare(self, session: SessionPair, plan: frozenset[LanguageId] = frozenset()) -> None:
        """Construct and warm only the adapters the session's requirement set names.

        Recognition, translation and voice requirements select the recogniser languages,
        the directed edges and the voices to warm; the voices of the spoken ``plan`` are
        warmed too. Nothing else is constructed or loaded.
        """
        with self._adapter_lock:
            self._prepare(session, frozenset(plan))

    def _prepare(self, session: SessionPair, plan: frozenset[LanguageId]) -> None:
        required = ordered_requirements(session)
        languages = tuple(
            str(item.subject) for item in required if item.kind is RequirementKind.RECOGNITION
        )
        edges = tuple(
            DirectedEdge.from_key(str(item.subject))
            for item in required
            if item.kind is RequirementKind.TRANSLATION
        )
        voices = tuple(str(item.subject) for item in required if item.kind is RequirementKind.VOICE)
        voices += tuple(
            item.id
            for item in self.registry.languages()
            if item.id in plan and item.id not in voices
        )
        if languages:
            _warm_up(self.speech_recognizer(), languages)
        if edges:
            _warm_up(self.text_translator(), edges)
        if voices:
            _warm_up(self.voice_synthesizer(), voices)
        if not session.mode.call_bridge:  # Call Bridge lanes synthesize on their own.
            # Conversation speaks exactly the plan its voice switches bound at Start.
            self.set_spoken_languages(plan)
        LOGGER.info(
            "Prepared session: recognition=%s translation=%s voices=%s",
            ",".join(languages) or "-",
            ",".join(edge.key for edge in edges) or "-",
            ",".join(voices) or "-",
        )

    def set_spoken_languages(self, languages: frozenset[LanguageId]) -> None:
        """The languages Conversation speaks; an empty set also clears the spoken plan."""
        self.spoken_languages = frozenset(languages)
        spoken = getattr(self, "spoken", None)
        if not self.spoken_languages and spoken is not None:
            spoken.clear_plan()
