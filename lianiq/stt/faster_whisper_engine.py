from __future__ import annotations

import logging
from collections.abc import Iterable
from pathlib import Path

import numpy as np

from lianiq.config import SpeechToTextConfig
from lianiq.domain import Transcript
from lianiq.hardware import ctranslate2_cuda_available, resolve_compute_device
from lianiq.languages.errors import CapabilityMissingError
from lianiq.languages.registry import BUILTIN_REGISTRY, LanguageId, LanguageRegistry
from lianiq.languages.requirements import Requirement, RequirementKind

LOGGER = logging.getLogger(__name__)

WHISPER_ENGINE = "whisper"


class FasterWhisperEngine:
    """One multilingual Whisper model; language IDs map through registry engine codes.

    Only languages listed in ``speech_to_text.languages`` can be forced; any other raises
    ``CapabilityMissingError``. A detected Whisper code maps back through the registry;
    an unregistered code yields ``Transcript.language = None`` and is never guessed.
    """

    def __init__(
        self,
        config: SpeechToTextConfig,
        model_path: Path,
        registry: LanguageRegistry = BUILTIN_REGISTRY,
    ) -> None:
        self.config = config
        self.model_path = model_path
        self.registry = registry
        self.languages: tuple[LanguageId, ...] = tuple(
            registry.get(language).id for language in config.languages
        )
        self.device = resolve_compute_device(config.device, ctranslate2_cuda_available())
        self._model = None

    def engine_code(self, language: str) -> str:
        """The Whisper code of a configured recognition language."""
        definition = self.registry.get(language)
        code = definition.engine_codes.get(WHISPER_ENGINE)
        if definition.id not in self.languages or code is None:
            raise CapabilityMissingError(Requirement(RequirementKind.RECOGNITION, definition.id))
        return code

    def _ensure_loaded(self):
        if self._model is not None:
            return self._model
        if not self.model_path.exists():
            raise FileNotFoundError(
                f"Whisper model is missing: {self.model_path}. "
                "Run scripts/download_models.py first."
            )
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise RuntimeError("faster-whisper is not installed") from exc
        LOGGER.info("Loading Faster-Whisper from %s", self.model_path)
        compute_type = self.config.compute_type
        if self.device == "cuda" and compute_type == "int8":
            compute_type = "int8_float16"
        self._model = WhisperModel(
            str(self.model_path),
            device=self.device,
            compute_type=compute_type,
            cpu_threads=self.config.cpu_threads,
            num_workers=1,
            local_files_only=True,
        )
        return self._model

    def warm_up(self, languages: Iterable[str]) -> None:
        """Load the model and run one silent pass for the first required language."""
        codes = [self.engine_code(language) for language in languages]
        if not codes:
            return
        model = self._ensure_loaded()
        segments, _ = model.transcribe(
            np.zeros(8_000, dtype=np.float32),
            language=codes[0],
            beam_size=1,
            best_of=1,
            temperature=0.0,
            condition_on_previous_text=False,
            vad_filter=False,
        )
        list(segments)

    def transcribe(
        self, samples: np.ndarray, sample_rate: int, language: LanguageId | None = None
    ) -> Transcript:
        if sample_rate != 16_000:
            raise ValueError("Faster-Whisper requires 16 kHz audio")
        forced_code = self.engine_code(language) if language is not None else None
        model = self._ensure_loaded()
        segments, info = model.transcribe(
            np.asarray(samples, dtype=np.float32),
            language=forced_code,
            beam_size=self.config.beam_size,
            best_of=1,
            temperature=0.0,
            condition_on_previous_text=False,
            vad_filter=False,
            word_timestamps=False,
        )
        text = " ".join(segment.text.strip() for segment in segments).strip()
        engine_code = str(getattr(info, "language", "") or "")
        probability = float(getattr(info, "language_probability", 0.0))
        detected = (
            self.registry.get(language).id
            if language is not None
            else self.registry.from_engine_code(WHISPER_ENGINE, engine_code)
        )
        if detected is None:
            LOGGER.warning("Whisper detected language '%s', which is not registered", engine_code)
        return Transcript(
            text=text,
            language=detected,
            probability=probability,
            duration_seconds=len(samples) / sample_rate,
            engine_language_code=engine_code,
        )
