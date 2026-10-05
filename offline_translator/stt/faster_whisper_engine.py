from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

from offline_translator.config import SpeechToTextConfig
from offline_translator.domain import Language, Transcript

LOGGER = logging.getLogger(__name__)


class FasterWhisperEngine:
    def __init__(self, config: SpeechToTextConfig, model_path: Path) -> None:
        self.config = config
        self.model_path = model_path
        self._model = None

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
        self._model = WhisperModel(
            str(self.model_path),
            device=self.config.device,
            compute_type=self.config.compute_type,
            cpu_threads=self.config.cpu_threads,
            num_workers=1,
            local_files_only=True,
        )
        return self._model

    def warm_up(self) -> None:
        model = self._ensure_loaded()
        segments, _ = model.transcribe(
            np.zeros(8_000, dtype=np.float32),
            language="de",
            beam_size=1,
            best_of=1,
            temperature=0.0,
            condition_on_previous_text=False,
            vad_filter=False,
        )
        list(segments)

    def transcribe(
        self, samples: np.ndarray, sample_rate: int, language: Language | None = None
    ) -> Transcript:
        if sample_rate != 16_000:
            raise ValueError("Faster-Whisper requires 16 kHz audio")
        model = self._ensure_loaded()
        segments, info = model.transcribe(
            np.asarray(samples, dtype=np.float32),
            language=language.value if language else None,
            beam_size=self.config.beam_size,
            best_of=1,
            temperature=0.0,
            condition_on_previous_text=False,
            vad_filter=False,
            word_timestamps=False,
        )
        text = " ".join(segment.text.strip() for segment in segments).strip()
        detected = _normalize_language(info.language)
        probability = float(getattr(info, "language_probability", 0.0))
        return Transcript(
            text=text,
            language=language or detected,
            probability=probability,
            duration_seconds=len(samples) / sample_rate,
        )


def _normalize_language(value: str) -> Language:
    normalized = value.lower().split("-")[0]
    if normalized == "de":
        return Language.GERMAN
    if normalized in {"zh", "cmn"}:
        return Language.MANDARIN
    raise ValueError(f"Detected language is not supported: {value}")
