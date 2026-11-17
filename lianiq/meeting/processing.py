"""The single inference worker of ``MeetingController`` (CAP-0177 contract.md §2-§5).

One thread takes contributions from the ``TurnQueue`` in speech-end order and runs them one
after the other: detection pass → language gate → (forced pass) → translation → speech →
playback. Serialising everything on one worker means playbacks never overlap. Before a
playback starts the worker asks the ``FeedbackGuard``; while a capture the output will mute
is mid-contribution it waits, at most ``max_playback_defer_ms``, then closes that
contribution (it is queued and processed, not dropped) and plays.

Logs carry roles, stage categories, counts and timings only: never recognised or translated
text and never audio (spec AC-17). Speech is synthesised and played in memory
(``synthesize_pcm``, ``play_pcm``): no audio file is written, not even a temporary one.
"""

from __future__ import annotations

import logging
import time

from lianiq.domain import TranslationResult
from lianiq.languages.capabilities import DirectedEdge
from lianiq.meeting.contracts import MeetingRole
from lianiq.meeting.events import MeetingEvent, MeetingEventKind, MeetingLine
from lianiq.meeting.feedback_guard import PlaybackDecision
from lianiq.meeting.language_gate import GateDecision
from lianiq.meeting.turn_queue import Contribution

LOGGER = logging.getLogger("lianiq.meeting.controller")
_TAKE_TIMEOUT = 0.05  # seconds; the worker never blocks forever on ``TurnQueue.take``
_DEFER_POLL = 0.01  # seconds between two ``before_playback`` checks


class _StageFailure(RuntimeError):
    def __init__(self, category: str) -> None:
        super().__init__(category)
        self.category = category


class ContributionProcessing:
    """``MeetingController`` base: the worker loop and one contribution's processing."""

    def _run(self) -> None:
        while True:
            if self._abort.is_set():
                self._abandon_queue()
                return
            item = self._queue.take(timeout=_TAKE_TIMEOUT)
            if item is None:
                if self._stopping.is_set() and not len(self._queue):
                    return  # drained: the captures are stopped and nothing is queued
                continue
            self._check_backlog()
            try:
                self._process(item)
            except Exception as exc:  # noqa: BLE001 - worker failure boundary.
                category = exc.category if isinstance(exc, _StageFailure) else "internal_failure"
                LOGGER.error(
                    "Meeting contribution failed: role=%s category=%s",
                    item.role.value,
                    category,
                )
                self._withdraw(item)

    def _check_backlog(self) -> None:
        with self._lock:
            behind = self._queue.falling_behind
            changed, self._behind = behind != self._behind, behind
        if changed:
            kind = MeetingEventKind.FALLING_BEHIND if behind else MeetingEventKind.CAUGHT_UP
            self._publish(MeetingEvent(kind, count=len(self._queue)))

    def _playback_state(self, target: MeetingRole, playing: bool) -> None:
        if not playing:
            self._guard.playback_ended(target)  # the guard tail starts now
            return
        self._guard.playback_started(target)
        language = (
            self.table_language if target is MeetingRole.TABLE_RENDER else self.local_language
        )
        for role in sorted(self._guard.muted_by(target)):  # table capture first
            if role not in self._lost:
                self._captures[role].mark_muted()
                self._publish(MeetingEvent(MeetingEventKind.MUTED, role, language=language))

    def _process(self, item: Contribution) -> None:
        role, gate = item.role, self._gates[item.role]
        utterance = item.utterance
        recognizer = self.engines.recognizer
        started = time.perf_counter()
        try:
            transcript = recognizer.transcribe(utterance.samples, utterance.sample_rate, None)
            decision = gate.decide(transcript)
            if decision is GateDecision.FORCE_EXPECTED:
                transcript = recognizer.transcribe(
                    utterance.samples, utterance.sample_rate, gate.expected
                )
        except Exception:  # noqa: BLE001 - external STT adapter boundary.
            raise _StageFailure("stt_failure") from None
        if decision is GateDecision.DISCARD:
            del transcript  # an other-language contribution keeps no text
            self._ignore(item)
            return
        del utterance  # the audio is released after STT
        stt_seconds = time.perf_counter() - started
        text = transcript.text.strip()
        if not text:
            self._withdraw(item)  # silence, not "other language"
            return
        if role is MeetingRole.USER_CAPTURE:
            self._line(item, text)  # the PO's recognised local-language text
        translated_started = time.perf_counter()
        try:
            edge = DirectedEdge(item.source_language, item.target_language)
            translated = self.engines.translator.translate(text, edge)
        except Exception:  # noqa: BLE001 - external translation adapter boundary.
            raise _StageFailure("translation_failure") from None
        translation_seconds = time.perf_counter() - translated_started
        tts_seconds = 0.0
        if role is MeetingRole.TABLE_CAPTURE:
            self._line(item, translated)  # the local-language translation
            if self._speak_local:
                tts_seconds = self._speak(
                    translated, item.target_language, MeetingRole.LOCAL_RENDER
                )
        else:
            tts_seconds = self._speak(translated, item.target_language, MeetingRole.TABLE_RENDER)
        result = TranslationResult(
            turn_id=item.contribution_id,
            captured_at=item.ended_at,
            source_text=text,
            translated_text=translated,
            source_language=item.source_language,
            target_language=item.target_language,
            stt_seconds=stt_seconds,
            translation_seconds=translation_seconds,
            tts_seconds=tts_seconds,
        )
        with self._lock:
            self._results.append(result)
        LOGGER.info(
            "Meeting contribution translated: role=%s stt_ms=%.1f translation_ms=%.1f "
            "tts_ms=%.1f queued=%d",
            role.value,
            stt_seconds * 1_000,
            translation_seconds * 1_000,
            tts_seconds * 1_000,
            len(self._queue),
        )

    def _speak(self, text: str, language, target: MeetingRole) -> float:
        """Synthesise and play ``text`` on ``target``; returns the synthesis seconds."""
        render = self._renders.get(target)
        if render is None or target in self._lost:
            return 0.0  # a lost render skips the speech; the text stays in the transcript
        started = time.perf_counter()
        try:
            samples, sample_rate = self.engines.synthesizer.synthesize_pcm(text, language)
        except Exception:  # noqa: BLE001 - external TTS adapter boundary.
            LOGGER.error("Meeting speech failed: target=%s category=tts_failure", target.value)
            return 0.0
        tts_seconds = time.perf_counter() - started
        try:
            self._await_quiet(target)
            if target not in self._lost:
                render.play_pcm(samples, sample_rate)
        except Exception:  # noqa: BLE001 - external playback adapter boundary.
            LOGGER.error("Meeting speech failed: target=%s category=playback_failure", target.value)
        return tts_seconds

    def _await_quiet(self, target: MeetingRole) -> None:
        """Wait while a capture ``target`` will mute is mid-contribution (contract §4)."""
        waiting_since = self._clock()
        while True:
            speaking = frozenset(
                role
                for role, capture in self._captures.items()
                if role not in self._lost and capture.speaking
            )
            decision = self._guard.before_playback(target, speaking, waiting_since)
            if decision is PlaybackDecision.PLAY:
                return
            if decision is PlaybackDecision.CLOSE_AND_PLAY:
                for role in sorted(speaking & self._guard.muted_by(target)):
                    self._captures[role].flush()
                return
            if self._abort.wait(_DEFER_POLL):
                return

    def _line(self, item: Contribution, text: str) -> None:
        line = MeetingLine(item.contribution_id, item.role, text, item.ended_at)
        self._publish(
            MeetingEvent(
                MeetingEventKind.LINE, item.role, contribution_id=item.contribution_id, line=line
            )
        )

    def _ignore(self, item: Contribution) -> None:
        with self._lock:
            self._ignored[item.role] += 1
            count = self._ignored[item.role]
        LOGGER.info("Meeting contribution ignored: role=%s reason=other_language", item.role.value)
        self._withdraw(item)
        self._publish(MeetingEvent(MeetingEventKind.IGNORED, item.role, count=count))

    def _withdraw(self, item: Contribution) -> None:
        if item.role is MeetingRole.TABLE_CAPTURE:
            self._publish(
                MeetingEvent(
                    MeetingEventKind.WITHDRAWN, item.role, contribution_id=item.contribution_id
                )
            )

    def _abandon_queue(self) -> None:
        """The drain timeout passed: the remaining contributions are withdrawn and counted."""
        abandoned = 0
        while (item := self._queue.take(timeout=0)) is not None:
            abandoned += 1
            self._withdraw(item)
        if abandoned:
            LOGGER.error("Meeting stop timed out: abandoned=%d", abandoned)
