"""``ListenPipeline``: the shared recogniser and translator, never a voice (contract.md §4).

The adapters are the shared pipeline's instances, fetched on each call, so one model copy
serves every mode and an adapter rebuild is picked up; so is the catalog. ``spoken`` stays ``None`` and
``spoken_languages`` stays empty, so the runner never speaks; ``voice_synthesizer`` raises,
so no path can synthesize or open an output stream. Context, epoch and held turns are its own.
"""

from __future__ import annotations

from lianiq.languages.errors import UnsupportedModeError
from lianiq.pipeline_translation import TranslationPipeline
from lianiq.pipeline_types import AdapterFactories, SpeechRecognizer, Synthesizer, Translator


class ListenPipeline(TranslationPipeline):
    def __init__(self, shared: TranslationPipeline) -> None:
        self._shared = shared
        super().__init__(
            registry=shared.registry, catalog=shared.catalog, factories=AdapterFactories()
        )

    @property
    def catalog(self):
        """The shared pipeline's catalog, so a readiness refresh after a pack job applies."""
        return self._shared.catalog

    @catalog.setter
    def catalog(self, _value) -> None:
        pass  # the shared pipeline owns it

    def speech_recognizer(self) -> SpeechRecognizer:
        return self._shared.speech_recognizer()

    def text_translator(self) -> Translator:
        return self._shared.text_translator()

    def voice_synthesizer(self) -> Synthesizer:
        raise UnsupportedModeError("Listen & translate never speaks")
