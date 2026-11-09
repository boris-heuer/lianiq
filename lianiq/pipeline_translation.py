"""``TranslationPipeline``: recognise, route and translate one turn (from ``pipeline.py``)."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from pathlib import Path
from uuid import UUID

import numpy as np

from lianiq.conversation.routing import HeldTurn, TurnRoute, TurnRouter
from lianiq.domain import AudioUtterance, TranslationResult
from lianiq.languages.capabilities import CapabilityCatalog, DirectedEdge
from lianiq.languages.errors import UnsupportedModeError
from lianiq.languages.modes import InputKind, RoutingKind, SessionPair
from lianiq.languages.registry import BUILTIN_REGISTRY, LanguageId, LanguageRegistry
from lianiq.pipeline_adapters import PipelineAdapters
from lianiq.pipeline_held import PipelineHeldTurns
from lianiq.pipeline_types import (
    DEFAULT_DETECTION_MIN_PROBABILITY,
    AdapterFactories,
    BoundUtterance,
    PipelineEvent,
    PipelineEventKind,
    SpeechRecognizer,
    Synthesizer,
    Translator,
    _RetainedTurn,
    bind_utterance,
)
from lianiq.translation.context import ContextBuffer

# The ``lianiq.pipeline`` logger, as before the move.
LOGGER = logging.getLogger("lianiq.pipeline")


class TranslationPipeline(PipelineAdapters, PipelineHeldTurns):
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
        self.turn_router = turn_router or TurnRouter(DEFAULT_DETECTION_MIN_PROBABILITY)
        self.factories = factories or AdapterFactories()
        self.registry = registry
        self.catalog = catalog
        # Notice events (``PipelineEvent``). Without a listener a playback failure raises as
        # before; with one, the turn's result is kept and spoken output stops (text-only).
        self.on_event: Callable[[PipelineEvent], None] | None = None
        # Serializes adapter construction and warm-up across Start requests.
        self._adapter_lock = threading.RLock()
        # Spoken output follows the started mode (``prepare``) or ``set_voice_output``.
        self.voice_output = synthesizer is not None
        # Serializes turn processing, held-turn resolution and context changes.
        self._turn_lock = threading.RLock()
        # Held turns with their retained audio, in memory only, until resolved or discarded.
        # Guarded by its own lock so the UI never waits for model inference to read or
        # discard them.
        self._held: dict[UUID, _RetainedTurn] = {}
        self._held_lock = threading.Lock()
        # The context has its own lock; a reset bumps the epoch so a turn that was already
        # running when the session stopped never feeds the next session's context.
        self._context_lock = threading.Lock()
        self._context_epoch = 0

    def process(self, item: BoundUtterance) -> TranslationResult | HeldTurn | None:
        """Recognise, route and translate one bound turn, or hold it if its language is unclear.

        Fixed routing forces the recogniser to the fixed source. Bidirectional routing
        detects the language; a held turn makes no translation call and keeps its audio
        until ``resolve``, ``discard`` or ``discard_held``.
        """
        session = item.session
        utterance = item.utterance
        forced = session.fixed_source if session.mode.routing is RoutingKind.FIXED else None
        with self._turn_lock:
            epoch = self._epoch()
            started = time.perf_counter()
            LOGGER.info(
                "Processing %.3f seconds of audio; routing=%s",
                utterance.samples.size / utterance.sample_rate,
                session.mode.routing.value,
            )
            transcript = self.speech_recognizer().transcribe(
                utterance.samples, utterance.sample_rate, forced
            )
            stt_seconds = time.perf_counter() - started
            if not transcript.text.strip():
                LOGGER.info("Speech recognition returned no text")
                return None
            route = self.turn_router.route(
                session, transcript, turn_id=item.turn_id, captured_at=item.captured_at
            )
            if isinstance(route, HeldTurn):
                with self._held_lock:
                    if self._epoch() != epoch:
                        # The session stopped while this turn ran: its held turns were
                        # already discarded, so this one is dropped with its audio too.
                        LOGGER.info("Unclear turn finished after the session stopped; dropped")
                        return None
                    self._held[route.turn_id] = _RetainedTurn(route, item)
                LOGGER.info(
                    "Turn held (%s): detected=%s probability=%.3f",
                    route.reason,
                    transcript.engine_language_code or transcript.language or "-",
                    transcript.probability,
                )
                return route
            LOGGER.info(
                "Speech recognition completed in %.3f seconds; source=%s probability=%.3f",
                stt_seconds,
                route.source,
                transcript.probability,
            )
            return self._translate(transcript.text, route, stt_seconds, item, epoch)

    def reset_context(self) -> None:
        """Clear the translation context (every session stop and pair or mode change).

        Never waits for a running turn.
        """
        self._end_context_epoch()

    def _end_context_epoch(self) -> None:
        with self._context_lock:
            self.context.clear()
            self._context_epoch += 1

    def translate_text(self, text: str, session: SessionPair) -> TranslationResult | None:
        """Typed input with fixed routing (requirement rows 1 and 2); no recogniser is used."""
        if session.mode.input is not InputKind.TYPED:
            raise UnsupportedModeError("Text input requires a typed usage mode")
        if not text.strip():
            return None
        source = session.fixed_source
        assert source is not None  # SessionPair rejects typed input without fixed routing
        item = bind_utterance(AudioUtterance(np.zeros(0, dtype=np.float32), 16_000), session)
        with self._turn_lock:
            route = TurnRoute(source, session.pair.other(source))
            return self._translate(text, route, 0.0, item, self._epoch())

    def _epoch(self) -> int:
        with self._context_lock:
            return self._context_epoch

    def _translate(
        self,
        text: str,
        route: TurnRoute,
        stt_seconds: float,
        item: BoundUtterance,
        epoch: int,
    ) -> TranslationResult:
        """Translate one routed turn; ``epoch`` is the context epoch when the turn started."""
        source, target = route.source, route.target
        with self._context_lock:
            stale = epoch != self._context_epoch
            context = () if stale else self.context.source_context(source)
        translated_started = time.perf_counter()
        translated = self.text_translator().translate(text, DirectedEdge(source, target), context)
        translation_seconds = time.perf_counter() - translated_started
        LOGGER.info("Translation completed in %.3f seconds", translation_seconds)
        with self._context_lock:
            if epoch == self._context_epoch:
                self.context.add(source, text, translated)

        tts_seconds = 0.0
        if self.voice_output and self.playback is not None:
            synthesizer = self.voice_synthesizer()
            tts_started = time.perf_counter()
            wav_path: Path | None = None
            if self.on_playback_state:
                self.on_playback_state(True)
            try:
                wav_path = synthesizer.synthesize(translated, target)
                tts_seconds = time.perf_counter() - tts_started
                LOGGER.info("Speech synthesis completed in %.3f seconds", tts_seconds)
                self._play(wav_path, target)
            finally:
                if wav_path:
                    wav_path.unlink(missing_ok=True)
                if self.on_playback_state:
                    self.on_playback_state(False)
        result = TranslationResult(
            turn_id=item.turn_id,
            captured_at=item.captured_at,
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

    def _play(self, wav_path: Path, language: LanguageId) -> None:
        """Play one synthesized turn; a failure is a notice event when someone listens."""
        assert self.playback is not None
        try:
            self.playback(wav_path, self.output_device)
        except Exception as exc:
            on_event = self.on_event
            if on_event is None:
                raise
            LOGGER.exception("Audio playback failed; spoken output stops for this session")
            # The speakers failed: the session continues text-only (spec §2.2.3 step 2).
            self.voice_output = False
            on_event(
                PipelineEvent(
                    PipelineEventKind.PLAYBACK_FAILED,
                    language=language,
                    message=f"{type(exc).__name__}: {exc}",
                )
            )
        else:
            LOGGER.info("Audio playback completed")
