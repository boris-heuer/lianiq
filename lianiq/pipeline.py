from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Protocol
from uuid import UUID, uuid4

import numpy as np

from lianiq.conversation.routing import HeldTurn, TurnRoute, TurnRouter
from lianiq.domain import AudioUtterance, Transcript, TranslationResult
from lianiq.languages.capabilities import CapabilityCatalog, DirectedEdge
from lianiq.languages.errors import UnsupportedModeError
from lianiq.languages.modes import InputKind, OutputKind, RoutingKind, SessionPair
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


@dataclass(frozen=True, slots=True)
class BoundUtterance:
    """A captured utterance bound to the session pair it was captured under.

    The worker routes and translates it with this binding, never with a live selection,
    so a queued turn keeps its languages when the session stops or the pair changes.
    """

    utterance: AudioUtterance
    session: SessionPair
    turn_id: UUID
    captured_at: datetime


def bind_utterance(utterance: AudioUtterance, session: SessionPair) -> BoundUtterance:
    return BoundUtterance(utterance, session, uuid4(), datetime.now().astimezone())


class PipelineEventKind(StrEnum):
    """Turn-level failures the shell shows as notices (CAP-0168 spec §2.3.4)."""

    QUEUE_OVERFLOW = "queue_overflow"  # the oldest pending segment was dropped
    TURNS_DROPPED = "turns_dropped"  # queued segments not translated before Stop
    PLAYBACK_FAILED = "playback_failed"  # spoken output failed; the turn stays as text


@dataclass(frozen=True, slots=True)
class PipelineEvent:
    """A notice event; ``message`` is technical detail for the local diagnostics log only."""

    kind: PipelineEventKind
    count: int = 1
    language: LanguageId | None = None
    message: str = ""


@dataclass(frozen=True, slots=True)
class _RetainedTurn:
    held: HeldTurn
    item: BoundUtterance  # the retained audio and its bound session pair


DEFAULT_DETECTION_MIN_PROBABILITY = 0.7  # settings v2 ``languages.detection_min_probability``


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

    def resolve(self, held: HeldTurn, source: LanguageId) -> TranslationResult | None:
        """Translate a held turn as ``source`` by forced re-recognition of its retained audio.

        Detection never runs again. The result keeps the held turn's ID and capture time.
        The turn is claimed before any model runs, so it can no longer be discarded while
        it is resolved; its audio is released when it is translated. On failure the turn
        is held again.

        The context epoch is taken when the turn is claimed. If the session stops (context
        reset or held-turn discard) before the resolution reaches translation, the
        resolution is dropped: it returns ``None``, its audio is released and nothing is
        translated, exactly like an unresolved held turn at **Stop**.
        """
        with self._held_lock:
            retained = self._held.get(held.turn_id)
            if retained is None:
                raise LookupError("The held turn is no longer pending")
            pair = retained.item.session.pair
            if source not in pair:
                raise UnsupportedModeError(f"{source!r} is not a member of the session pair")
            del self._held[held.turn_id]  # claimed: no longer held, not discardable
            claimed_epoch = self._epoch()
        item = retained.item
        try:
            with self._turn_lock:
                if self._epoch() != claimed_epoch:
                    LOGGER.info("The session stopped before the held turn was resolved; dropped")
                    return None
                epoch = claimed_epoch
                started = time.perf_counter()
                transcript = self.speech_recognizer().transcribe(
                    item.utterance.samples, item.utterance.sample_rate, source
                )
                stt_seconds = time.perf_counter() - started
                if self._epoch() != epoch:
                    LOGGER.info("The session stopped while the held turn was re-recognised")
                    return None
                if not transcript.text.strip():
                    LOGGER.info("Forced re-recognition returned no text; the turn was dropped")
                    return None
                return self._translate(
                    transcript.text,
                    TurnRoute(source, pair.other(source)),
                    stt_seconds,
                    item,
                    epoch,
                )
        except BaseException:
            with self._held_lock:
                # Held again only within its session; after Stop it is dropped with its audio.
                if self._epoch() == claimed_epoch:
                    self._held[held.turn_id] = retained
            raise

    def discard(self, held: HeldTurn) -> bool:
        """Drop a held turn and release its audio; it leaves no result and no export line.

        Returns ``False`` if the turn is no longer held (resolved, being resolved or
        already discarded).
        """
        with self._held_lock:
            return self._held.pop(held.turn_id, None) is not None

    def discard_held(self) -> tuple[HeldTurn, ...]:
        """Discard every unresolved held turn (session stop); returns them by capture time.

        This also ends the context epoch under the held-turn lock, so a resolution that
        claimed its turn before this call is dropped instead of surviving the stop.
        """
        with self._held_lock:
            discarded = self._sorted_held()
            self._held.clear()
            self._end_context_epoch()
        return discarded

    def held_turns(self) -> tuple[HeldTurn, ...]:
        """The unresolved held turns ordered by capture time."""
        with self._held_lock:
            return self._sorted_held()

    def _sorted_held(self) -> tuple[HeldTurn, ...]:
        return tuple(sorted((entry.held for entry in self._held.values()), key=_captured_at))

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


def _captured_at(held: HeldTurn) -> datetime:
    return held.captured_at


class PipelineRunner:
    """Single-consumer worker with bounded backlog to preserve conversational latency.

    ``start(session)`` binds the session pair; every submitted utterance carries that
    binding (``BoundUtterance``), so the worker never reads a live selection. ``stop``
    finishes the already-queued items with their bound pair within the timeout and
    reports every item it could not finish as dropped.
    """

    def __init__(
        self,
        pipeline: TranslationPipeline,
        on_result: Callable[[TranslationResult], None],
        on_error: Callable[[str], None],
        on_busy: Callable[[bool], None] | None = None,
        on_held: Callable[[HeldTurn], None] | None = None,
        max_pending: int = 2,
        on_event: Callable[[PipelineEvent], None] | None = None,
    ) -> None:
        self.pipeline = pipeline
        self.on_result = on_result
        self.on_error = on_error
        self.on_busy = on_busy
        self.on_held = on_held
        # Overflow and dropped turns are notice events; without a listener they are
        # reported through ``on_error`` as text, as before.
        self.on_event = on_event
        self.max_pending = max_pending
        self._queue: queue.Queue[BoundUtterance | None] = queue.Queue(maxsize=max_pending)
        self._thread: threading.Thread | None = None
        self._session: SessionPair | None = None
        self._accepting = False
        self._abort = threading.Event()
        # Taking an item and aborting are atomic, so every item is either started or dropped.
        self._take_lock = threading.Lock()

    @property
    def session(self) -> SessionPair | None:
        """The session pair new utterances are bound to, or ``None`` when stopped."""
        return self._session

    def start(self, session: SessionPair) -> None:
        if self._thread and self._thread.is_alive():
            raise RuntimeError("The pipeline worker is still running; stop it first")
        self._queue = queue.Queue(maxsize=self.max_pending)
        self._abort.clear()
        self._session = session
        self._accepting = True
        self._thread = threading.Thread(target=self._run, name="translation-pipeline", daemon=True)
        self._thread.start()

    def submit(self, utterance: AudioUtterance) -> None:
        session = self._session
        if not self._accepting or session is None:
            return
        item = bind_utterance(utterance, session)
        try:
            self._queue.put_nowait(item)
        except queue.Full:
            # Drop the oldest waiting utterance: stale speech is worse than a visible warning.
            try:
                self._queue.get_nowait()
                self._queue.task_done()
                self._queue.put_nowait(item)
            except queue.Empty:
                pass
            if self.on_event is not None:
                self.on_event(PipelineEvent(PipelineEventKind.QUEUE_OVERFLOW))
            else:
                self.on_error("The audio queue was full; the oldest pending segment was dropped.")

    def resolve(
        self,
        held: HeldTurn,
        source: LanguageId,
        on_done: Callable[[], None] | None = None,
    ) -> threading.Thread:
        """Resolve a held turn in the background; the result arrives through ``on_result``.

        ``on_done`` runs after every outcome (result, dropped or error).
        """

        def run() -> None:
            if self.on_busy:
                self.on_busy(True)
            try:
                result = self.pipeline.resolve(held, source)
                if result is not None:
                    self.on_result(result)
            except Exception as exc:
                LOGGER.exception("Held turn resolution failed")
                self.on_error(str(exc))
            finally:
                if self.on_busy:
                    self.on_busy(False)
                if on_done is not None:
                    on_done()

        thread = threading.Thread(target=run, name="held-turn-resolution", daemon=True)
        thread.start()
        return thread

    def stop(self, timeout: float = 10.0) -> int:
        """Stop accepting audio, finish queued items, and return how many were dropped.

        Queued items are processed with their bound pair until ``timeout``. Items not yet
        started by then are dropped and reported through ``on_error``; a turn already being
        processed completes and its result is still delivered.
        """
        self._accepting = False
        self._session = None
        thread = self._thread
        if thread is None:
            return self._drain()
        deadline = time.monotonic() + timeout
        try:
            self._queue.put(None, timeout=max(0.0, deadline - time.monotonic()))
        except queue.Full:
            pass
        thread.join(timeout=max(0.0, deadline - time.monotonic()))
        if thread.is_alive():
            with self._take_lock:
                self._abort.set()
                dropped = self._drain()
            LOGGER.warning(
                "Pipeline worker did not finish within %.1f seconds; %d queued item(s) dropped",
                timeout,
                dropped,
            )
            if dropped:
                self._report_dropped(dropped)
            return dropped
        self._thread = None
        return 0

    def _report_dropped(self, dropped: int) -> None:
        if self.on_event is not None:
            self.on_event(PipelineEvent(PipelineEventKind.TURNS_DROPPED, count=dropped))
            return
        self.on_error(
            f"{dropped} queued speech segment(s) were not translated before the "
            "session stopped and were dropped."
        )

    def _drain(self) -> int:
        dropped = 0
        while True:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                return dropped
            self._queue.task_done()
            if item is not None:
                dropped += 1

    def _run(self) -> None:
        while True:
            # Taking an item and ``stop``'s abort are atomic: an item taken here is started,
            # an item still queued at abort is counted in ``stop``'s dropped count. The worker
            # never drops an item on its own, so ``StopReport.dropped`` is complete. ``stop``
            # waits at most the 0.2 s poll interval for this lock.
            with self._take_lock:
                if self._abort.is_set():
                    return
                try:
                    item = self._queue.get(timeout=0.2)
                except queue.Empty:
                    continue
            try:
                if item is None:
                    return
                if self.on_busy:
                    self.on_busy(True)
                outcome = self.pipeline.process(item)
                if isinstance(outcome, HeldTurn):
                    if self.on_held:
                        self.on_held(outcome)
                elif outcome is not None:
                    self.on_result(outcome)
            except Exception as exc:
                LOGGER.exception("Translation pipeline failed")
                self.on_error(str(exc))
            finally:
                if self.on_busy and item is not None:
                    self.on_busy(False)
                self._queue.task_done()
