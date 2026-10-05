from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

import numpy as np

from offline_translator.conversation.routing import TurnRouter
from offline_translator.domain import (
    AudioUtterance,
    ConversationMode,
    Language,
    Transcript,
    TranslationResult,
)
from offline_translator.translation.context import ContextBuffer

LOGGER = logging.getLogger(__name__)


class SpeechRecognizer(Protocol):
    def transcribe(
        self, samples: np.ndarray, sample_rate: int, language: Language | None = None
    ) -> Transcript: ...


class Translator(Protocol):
    def translate(
        self,
        text: str,
        source: Language,
        target: Language,
        context: tuple[str, ...] = (),
    ) -> str: ...


class Synthesizer(Protocol):
    def synthesize(self, text: str, language: Language) -> Path: ...


class TranslationPipeline:
    def __init__(
        self,
        recognizer: SpeechRecognizer,
        translator: Translator,
        synthesizer: Synthesizer | None,
        playback: Callable[[Path, int | None], None] | None,
        context_sentences: int = 5,
        output_device: int | None = None,
        on_playback_state: Callable[[bool], None] | None = None,
        turn_router: TurnRouter | None = None,
    ) -> None:
        self.recognizer = recognizer
        self.translator = translator
        self.synthesizer = synthesizer
        self.playback = playback
        self.context = ContextBuffer(context_sentences)
        self.output_device = output_device
        self.on_playback_state = on_playback_state
        self.turn_router = turn_router or TurnRouter()

    def warm_up(self) -> None:
        for component in (self.recognizer, self.translator, self.synthesizer):
            if component is not None and hasattr(component, "warm_up"):
                component.warm_up()

    def process(
        self, utterance: AudioUtterance, mode: ConversationMode
    ) -> TranslationResult | None:
        forced_source = mode.forced_source
        started = time.perf_counter()
        LOGGER.info(
            "Processing %.3f seconds of audio in mode %s",
            utterance.samples.size / utterance.sample_rate,
            mode.value,
        )
        transcript = self.recognizer.transcribe(
            utterance.samples, utterance.sample_rate, forced_source
        )
        stt_seconds = time.perf_counter() - started
        if not transcript.text.strip():
            LOGGER.info("Speech recognition returned no text")
            return None
        route = self.turn_router.route(mode, transcript.language)
        source = route.source
        target = route.target
        LOGGER.info(
            "Speech recognition completed in %.3f seconds; source=%s probability=%.3f",
            stt_seconds,
            source.value,
            transcript.probability,
        )

        translated_started = time.perf_counter()
        translated = self.translator.translate(
            transcript.text,
            source,
            target,
            self.context.source_context(source),
        )
        translation_seconds = time.perf_counter() - translated_started
        LOGGER.info("Translation completed in %.3f seconds", translation_seconds)
        self.context.add(source, transcript.text, translated)

        tts_seconds = 0.0
        if self.synthesizer is not None and self.playback is not None:
            tts_started = time.perf_counter()
            wav_path: Path | None = None
            if self.on_playback_state:
                self.on_playback_state(True)
            try:
                wav_path = self.synthesizer.synthesize(translated, target)
                tts_seconds = time.perf_counter() - tts_started
                LOGGER.info("Speech synthesis completed in %.3f seconds", tts_seconds)
                self.playback(wav_path, self.output_device)
                LOGGER.info("Audio playback completed")
            finally:
                if wav_path:
                    wav_path.unlink(missing_ok=True)
                if self.on_playback_state:
                    self.on_playback_state(False)
        result = TranslationResult(
            source_text=transcript.text,
            translated_text=translated,
            source_language=source,
            target_language=target,
            stt_seconds=stt_seconds,
            translation_seconds=translation_seconds,
            tts_seconds=tts_seconds,
        )
        LOGGER.info("Pipeline completed in %.3f seconds", result.total_seconds)
        return result


class PipelineRunner:
    """Single-consumer worker with bounded backlog to preserve conversational latency."""

    def __init__(
        self,
        pipeline: TranslationPipeline,
        mode_provider: Callable[[], ConversationMode],
        on_result: Callable[[TranslationResult], None],
        on_error: Callable[[str], None],
        on_busy: Callable[[bool], None] | None = None,
    ) -> None:
        self.pipeline = pipeline
        self.mode_provider = mode_provider
        self.on_result = on_result
        self.on_error = on_error
        self.on_busy = on_busy
        self._queue: queue.Queue[AudioUtterance | None] = queue.Queue(maxsize=2)
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._queue = queue.Queue(maxsize=2)
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="translation-pipeline", daemon=True)
        self._thread.start()

    def submit(self, utterance: AudioUtterance) -> None:
        if self._stop.is_set():
            return
        try:
            self._queue.put_nowait(utterance)
        except queue.Full:
            # Drop the oldest waiting utterance: stale speech is worse than a visible warning.
            try:
                self._queue.get_nowait()
                self._queue.task_done()
                self._queue.put_nowait(utterance)
            except queue.Empty:
                pass
            self.on_error("The audio queue was full; the oldest pending segment was dropped.")

    def stop(self, timeout: float = 10.0) -> None:
        self._stop.set()
        while True:
            try:
                self._queue.get_nowait()
                self._queue.task_done()
            except queue.Empty:
                break
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass
        if self._thread:
            self._thread.join(timeout=timeout)
            if self._thread.is_alive():
                LOGGER.warning("Pipeline worker did not stop within %.1f seconds", timeout)
                return
        self._thread = None

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                item = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                if item is None:
                    return
                if self.on_busy:
                    self.on_busy(True)
                result = self.pipeline.process(item, self.mode_provider())
                if result:
                    self.on_result(result)
            except Exception as exc:
                LOGGER.exception("Translation pipeline failed")
                self.on_error(str(exc))
            finally:
                if self.on_busy:
                    self.on_busy(False)
                self._queue.task_done()
