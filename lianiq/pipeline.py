from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np

from lianiq.conversation.routing import TurnRouter
from lianiq.domain import (
    AudioUtterance,
    ConversationMode,
    Language,
    Transcript,
    TranslationResult,
)
from lianiq.languages.capabilities import CapabilityCatalog, DirectedEdge
from lianiq.languages.errors import UnsupportedModeError
from lianiq.languages.modes import InputKind, OutputKind, SessionPair
from lianiq.languages.registry import BUILTIN_REGISTRY, LanguageId, LanguageRegistry
from lianiq.languages.requirements import RequirementKind, ordered_requirements
from lianiq.translation.context import ContextBuffer

LOGGER = logging.getLogger(__name__)


# Adapter protocols (CAP-0169 contract.md §3.1.6): every adapter is keyed by language ID
# or directed edge and raises ``CapabilityMissingError`` for an unconfigured one.
class SpeechRecognizer(Protocol):
    def transcribe(
        self, samples: np.ndarray, sample_rate: int, language: LanguageId | None = None
    ) -> Transcript: ...


class Translator(Protocol):
    def translate(self, text: str, edge: DirectedEdge, context: tuple[str, ...] = ()) -> str: ...


class Synthesizer(Protocol):
    def synthesize(self, text: str, language: LanguageId) -> Path: ...


@dataclass(frozen=True, slots=True)
class AdapterFactories:
    """Adapter constructors, each called at most once and only when a mode requires it."""

    recognizer: Callable[[], SpeechRecognizer] | None = None
    translator: Callable[[], Translator] | None = None
    synthesizer: Callable[[], Synthesizer] | None = None


class UnroutedTurnError(RuntimeError):
    """A recognised turn's language is not part of the language pair; nothing is translated."""

    def __init__(self, detected: str) -> None:
        super().__init__(
            f"Detected language {detected!r} is not part of the language pair; "
            "the turn was not translated."
        )
        self.detected = detected


def _warm_up(component: object, subjects: tuple[object, ...]) -> None:
    warm_up = getattr(component, "warm_up", None)
    if warm_up is not None:
        warm_up(subjects)


class TranslationPipeline:
    def __init__(
        self,
        recognizer: SpeechRecognizer | None = None,
        translator: Translator | None = None,
        synthesizer: Synthesizer | None = None,
        playback: Callable[[Path, int | None], None] | None = None,
        context_sentences: int = 5,
        output_device: int | None = None,
        on_playback_state: Callable[[bool], None] | None = None,
        turn_router: TurnRouter | None = None,
        *,
        factories: AdapterFactories | None = None,
        registry: LanguageRegistry = BUILTIN_REGISTRY,
        catalog: CapabilityCatalog | None = None,
    ) -> None:
        self.recognizer = recognizer
        self.translator = translator
        self.synthesizer = synthesizer
        self.playback = playback
        self.context = ContextBuffer(context_sentences)
        self.output_device = output_device
        self.on_playback_state = on_playback_state
        self.turn_router = turn_router or TurnRouter()
        self.factories = factories or AdapterFactories()
        self.registry = registry
        self.catalog = catalog
        # Serializes adapter construction and warm-up across Start requests.
        self._adapter_lock = threading.RLock()
        # Spoken output follows the started mode (``prepare``) or ``set_voice_output``.
        self.voice_output = synthesizer is not None

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
        transcript = self.speech_recognizer().transcribe(
            utterance.samples,
            utterance.sample_rate,
            forced_source.id if forced_source else None,
        )
        stt_seconds = time.perf_counter() - started
        if not transcript.text.strip():
            LOGGER.info("Speech recognition returned no text")
            return None
        detected = Language.from_id(transcript.language)
        if forced_source is None and detected is None:
            # No script-based or other guess: an unknown language is never translated.
            raise UnroutedTurnError(transcript.engine_language_code or str(transcript.language))
        route = self.turn_router.route(mode, forced_source or detected)
        LOGGER.info(
            "Speech recognition completed in %.3f seconds; source=%s probability=%.3f",
            stt_seconds,
            route.source.id,
            transcript.probability,
        )
        return self._translate(transcript.text, route.source, route.target, stt_seconds)

    def translate_text(self, text: str, session: SessionPair) -> TranslationResult | None:
        """Typed input with fixed routing (requirement rows 1 and 2); no recogniser is used."""
        if session.mode.input is not InputKind.TYPED:
            raise UnsupportedModeError("Text input requires a typed usage mode")
        source = Language.from_id(session.fixed_source)
        target = Language.from_id(session.fixed_target)
        if source is None or target is None:
            raise UnsupportedModeError(
                f"Unsupported fixed direction {session.fixed_source}>{session.fixed_target}"
            )
        if not text.strip():
            return None
        return self._translate(text, source, target, 0.0)

    def _translate(
        self, text: str, source: Language, target: Language, stt_seconds: float
    ) -> TranslationResult:
        translated_started = time.perf_counter()
        translated = self.text_translator().translate(
            text,
            DirectedEdge(source.id, target.id),
            self.context.source_context(source.id),
        )
        translation_seconds = time.perf_counter() - translated_started
        LOGGER.info("Translation completed in %.3f seconds", translation_seconds)
        self.context.add(source.id, text, translated)

        tts_seconds = 0.0
        if self.voice_output and self.playback is not None:
            synthesizer = self.voice_synthesizer()
            tts_started = time.perf_counter()
            wav_path: Path | None = None
            if self.on_playback_state:
                self.on_playback_state(True)
            try:
                wav_path = synthesizer.synthesize(translated, target.id)
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
            source_text=text,
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
