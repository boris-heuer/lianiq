"""The recognise-translate-speak stage of ``TranslationLane`` (from ``translation_lane.py``)."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from lianiq.call_bridge.contracts import BridgeEventKind
from lianiq.call_bridge.health import LaneHealthSnapshot
from lianiq.domain import AudioUtterance, TranslationResult

# The ``lianiq.call_bridge.translation_lane`` logger, as before the move.
LOGGER = logging.getLogger("lianiq.call_bridge.translation_lane")


class Playback(Protocol):
    def __call__(self, output: Path | str) -> None: ...


class _StageFailure(RuntimeError):
    def __init__(self, category: str) -> None:
        super().__init__(category)
        self.category = category


@dataclass(frozen=True, slots=True)
class _PendingUtterance:
    sequence: int
    enqueued_at: float
    utterance: AudioUtterance
    captured_at: datetime


class LaneProcessing:
    """``TranslationLane`` base: one utterance through STT, translation, TTS and playback."""

    def _process(self, item: _PendingUtterance) -> None:
        utterance = item.utterance
        started = time.perf_counter()
        try:
            transcript = self.recognizer.transcribe(
                utterance.samples,
                utterance.sample_rate,
                self.source_language,
            )
        except Exception:  # noqa: BLE001 - external STT adapter boundary.
            raise _StageFailure("stt_failure") from None
        stt_seconds = time.perf_counter() - started
        if not transcript.text.strip():
            return
        translated_started = time.perf_counter()
        try:
            translated = self.translator.translate(transcript.text, self._edge)
        except Exception:  # noqa: BLE001 - external translation adapter boundary.
            raise _StageFailure("translation_failure") from None
        translation_seconds = time.perf_counter() - translated_started
        tts_started = time.perf_counter()
        try:
            output = self.synthesizer.synthesize(translated, self.target_language)
        except Exception:  # noqa: BLE001 - external TTS adapter boundary.
            raise _StageFailure("tts_failure") from None
        tts_seconds = time.perf_counter() - tts_started
        playback_started = time.perf_counter()
        try:
            if not self._available.is_set():
                self._emit(
                    BridgeEventKind.DROPPED,
                    "lane_unavailable",
                    "synthesized_output_muted",
                    item.sequence,
                )
                return
            try:
                self.playback(output)
            except Exception:  # noqa: BLE001 - external playback adapter boundary.
                raise _StageFailure("playback_failure") from None
        finally:
            if isinstance(output, Path):
                output.unlink(missing_ok=True)
        playback_seconds = time.perf_counter() - playback_started
        result = TranslationResult(
            turn_id=uuid4(),
            captured_at=item.captured_at,
            source_text=transcript.text,
            translated_text=translated,
            source_language=self.source_language,
            target_language=self.target_language,
            stt_seconds=stt_seconds,
            translation_seconds=translation_seconds,
            tts_seconds=tts_seconds,
        )
        if self.on_result:
            self.on_result(result)
        with self._health_lock:
            self._health = LaneHealthSnapshot(
                captured_seconds=utterance.samples.size / utterance.sample_rate,
                queue_age_ms=self._health.queue_age_ms,
                dropped_turns=self._health.dropped_turns,
                stt_ms=stt_seconds * 1_000,
                translation_ms=translation_seconds * 1_000,
                tts_ms=tts_seconds * 1_000,
                playback_ms=playback_seconds * 1_000,
            )
        LOGGER.info(
            "Call bridge lane metrics: lane=%s captured_ms=%.1f queue_ms=%.1f "
            "stt_ms=%.1f translation_ms=%.1f tts_ms=%.1f playback_ms=%.1f dropped=%d",
            self.lane_id.value,
            self._health.captured_seconds * 1_000,
            self._health.queue_age_ms,
            self._health.stt_ms,
            self._health.translation_ms,
            self._health.tts_ms,
            self._health.playback_ms,
            self._health.dropped_turns,
        )
