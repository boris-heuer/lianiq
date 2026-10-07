from __future__ import annotations

import sys
import wave

from lianiq.app import build_pipeline
from lianiq.audio.wav import read_pcm16_mono
from lianiq.call_bridge.contracts import LaneId
from lianiq.call_bridge.inference_scheduler import InferenceScheduler
from lianiq.call_bridge.translation_lane import TranslationLane
from lianiq.config import AppConfig
from lianiq.domain import Language

MAX_END_TO_END_SECONDS = 3.0
WAIT_TIMEOUT_SECONDS = 30.0


def validate_wav(path) -> None:
    with wave.open(str(path), "rb") as wav_file:
        if wav_file.getnframes() <= 0:
            raise ValueError("Synthesized route output contains no audio frames")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    config = AppConfig.load()
    config.tts.enabled = True
    pipeline, synthesizer = build_pipeline(config)
    pipeline.warm_up()

    scheduler = InferenceScheduler(max_concurrent=2)
    results = {}
    output_counts = {LaneId.OUTBOUND: 0, LaneId.INBOUND: 0}

    def playback(lane_id, path) -> None:
        validate_wav(path)
        output_counts[lane_id] += 1

    def record(lane_id, result) -> None:
        results[lane_id] = result

    lanes = {
        LaneId.OUTBOUND: TranslationLane(
            LaneId.OUTBOUND,
            Language.GERMAN,
            Language.MANDARIN,
            pipeline.recognizer,
            pipeline.translator,
            synthesizer,
            lambda path: playback(LaneId.OUTBOUND, path),
            scheduler,
            max_pending_age_ms=config.call_bridge.max_pending_age_ms,
            on_result=lambda result: record(LaneId.OUTBOUND, result),
        ),
        LaneId.INBOUND: TranslationLane(
            LaneId.INBOUND,
            Language.MANDARIN,
            Language.GERMAN,
            pipeline.recognizer,
            pipeline.translator,
            synthesizer,
            lambda path: playback(LaneId.INBOUND, path),
            scheduler,
            max_pending_age_ms=config.call_bridge.max_pending_age_ms,
            on_result=lambda result: record(LaneId.INBOUND, result),
        ),
    }
    sources = {
        LaneId.OUTBOUND: ("Guten Morgen.", Language.GERMAN),
        LaneId.INBOUND: ("我们下午三点开会。", Language.MANDARIN),
    }
    utterances = {}
    for lane_id, (text, language) in sources.items():
        path = synthesizer.synthesize(text, language)
        try:
            utterances[lane_id] = read_pcm16_mono(path)
        finally:
            path.unlink(missing_ok=True)

    for lane in lanes.values():
        lane.start()
    for lane_id, lane in lanes.items():
        lane.submit(utterances[lane_id])

    passed = True
    for lane_id, lane in lanes.items():
        idle = lane.wait_until_idle(WAIT_TIMEOUT_SECONDS)
        stopped = lane.stop(timeout=5.0)
        result = results.get(lane_id)
        health = lane.health
        elapsed = (
            health.queue_age_ms
            + health.stt_ms
            + health.translation_ms
            + health.tts_ms
            + health.playback_ms
        ) / 1_000
        case_passed = (
            idle
            and stopped
            and result is not None
            and output_counts[lane_id] == 1
            and elapsed <= MAX_END_TO_END_SECONDS
        )
        passed = passed and case_passed
        print(
            f"{'PASS' if case_passed else 'FAIL'} {lane_id.value}: "
            f"end_to_end={elapsed:.3f}s queue={health.queue_age_ms / 1000:.3f}s "
            f"dropped={health.dropped_turns} outputs={output_counts[lane_id]}"
        )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
