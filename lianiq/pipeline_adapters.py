"""Requirement-scoped adapter construction of ``TranslationPipeline`` (from ``pipeline.py``)."""

from __future__ import annotations

import logging

from lianiq.languages.capabilities import DirectedEdge
from lianiq.languages.modes import OutputKind, SessionPair
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

    def _construct(self, name: str):
        factory = getattr(self.factories, name)
        if factory is None:
            raise RuntimeError(f"No speech {name} adapter is configured")
        LOGGER.info("Constructing the %s adapter", name)
        return factory()

    def prepare(self, session: SessionPair) -> None:
        """Construct and warm only the adapters the session's requirement set names.

        Recognition, translation and voice requirements select the recogniser languages,
        the directed edges and the voices to warm; nothing else is constructed or loaded.
        """
        with self._adapter_lock:
            self._prepare(session)

    def _prepare(self, session: SessionPair) -> None:
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
        if languages:
            _warm_up(self.speech_recognizer(), languages)
        if edges:
            _warm_up(self.text_translator(), edges)
        if voices:
            _warm_up(self.voice_synthesizer(), voices)
        if not session.mode.call_bridge:  # Call Bridge lanes synthesize on their own.
            self.voice_output = session.mode.output is OutputKind.SPOKEN
        LOGGER.info(
            "Prepared session: recognition=%s translation=%s voices=%s",
            ",".join(languages) or "-",
            ",".join(edge.key for edge in edges) or "-",
            ",".join(voices) or "-",
        )

    def set_voice_output(self, enabled: bool) -> None:
        """Switch spoken output; the voice adapter is constructed on its first use."""
        self.voice_output = enabled
