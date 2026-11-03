"""Call Bridge lane self-test (e2e row C-03).

Without arguments it runs both lanes over the configured offline models and validates the
synthesized WAV output in memory. ``--synthetic`` needs no models: it runs the lanes and the
full-duplex controller over synthetic adapters and endpoints, and checks that the lanes are
``local>remote`` and ``remote>local`` for the whole session and that a missing lane voice
fails closed before any lane starts, naming that voice.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np

from lianiq.call_bridge.contracts import (
    AudioEndpointRef,
    BridgeState,
    CallBridgeLanes,
    EndpointFlow,
    EndpointRole,
    LaneId,
)
from lianiq.call_bridge.controller import FullDuplexBridgeController, check_call_bridge
from lianiq.call_bridge.inference_scheduler import InferenceScheduler
from lianiq.call_bridge.translation_lane import TranslationLane
from lianiq.config import AppConfig
from lianiq.domain import AudioUtterance, Transcript
from lianiq.languages.capabilities import CapabilityCatalog, ReadinessProbe
from lianiq.languages.errors import ModeUnavailableError
from lianiq.languages.modes import CALL_BRIDGE_MODE, SessionPair
from lianiq.languages.registry import BUILTIN_REGISTRY, LanguageId, LanguageRegistry
from lianiq.languages.requirements import Requirement, RequirementKind, describe

MAX_END_TO_END_SECONDS = 3.0
WAIT_TIMEOUT_SECONDS = 30.0
# Source phrases per language for the model-backed run (functional data).
SOURCE_TEXT = {LanguageId("de"): "Guten Morgen.", LanguageId("zh-Hans"): "我们下午三点开会。"}


def validate_wav(path) -> None:
    with wave.open(str(path), "rb") as wav_file:
        if wav_file.getnframes() <= 0:
            raise ValueError("Synthesized route output contains no audio frames")


def call_bridge_session(config: AppConfig, registry: LanguageRegistry) -> SessionPair:
    return SessionPair(
        registry.pair(*config.languages.pair),
        CALL_BRIDGE_MODE,
        local_language=registry.get(config.call_bridge.local_language).id,
    )


def run_models(config: AppConfig) -> int:
    from lianiq.app import build_pipeline
    from lianiq.audio.wav import read_pcm16_mono

    config.voice_output = True
    pipeline = build_pipeline(config)
    registry = pipeline.registry
    session = call_bridge_session(config, registry)
    lanes = CallBridgeLanes.from_session(session)
    # The model run validates the WAV output in memory instead of using call endpoints.
    availability = check_call_bridge(session, pipeline.catalog, EndpointRole)
    if not availability.available:
        names = ", ".join(describe(item, registry) for item in availability.missing)
        print(f"FAIL prepare: not available: missing {names}")
        return 1
    pipeline.prepare(session)
    recognizer = pipeline.speech_recognizer()
    translator = pipeline.text_translator()
    synthesizer = pipeline.voice_synthesizer()

    scheduler = InferenceScheduler(max_concurrent=2)
    results = {}
    output_counts = {LaneId.OUTBOUND: 0, LaneId.INBOUND: 0}

    def playback(lane_id, path) -> None:
        validate_wav(path)
        output_counts[lane_id] += 1

    def record(lane_id, result) -> None:
        results[lane_id] = result

    lanes_by_id = {
        lane_id: TranslationLane(
            lane_id,
            lanes.edge(lane_id),
            recognizer,
            translator,
            synthesizer,
            lambda path, lane_id=lane_id: playback(lane_id, path),
            scheduler,
            max_pending_age_ms=config.call_bridge.max_pending_age_ms,
            on_result=lambda result, lane_id=lane_id: record(lane_id, result),
        )
        for lane_id in LaneId
    }
    utterances = {}
    for lane_id, lane in lanes_by_id.items():
        source = lane.edge.source
        text = SOURCE_TEXT.get(source)
        if text is None:
            print(f"FAIL {lane_id.value}: no source phrase for {registry.display_name(source)}")
            return 1
        path = synthesizer.synthesize(text, source)
        try:
            utterances[lane_id] = read_pcm16_mono(path)
        finally:
            path.unlink(missing_ok=True)

    for lane in lanes_by_id.values():
        lane.start()
    for lane_id, lane in lanes_by_id.items():
        lane.submit(utterances[lane_id])

    passed = True
    for lane_id, lane in lanes_by_id.items():
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
            f"{'PASS' if case_passed else 'FAIL'} {lane_id.value} {lane.edge.key}: "
            f"end_to_end={elapsed:.3f}s queue={health.queue_age_ms / 1000:.3f}s "
            f"dropped={health.dropped_turns} outputs={output_counts[lane_id]}"
        )
    return 0 if passed else 1


class _SyntheticRecognizer:
    def transcribe(self, samples, sample_rate, language=None):
        return Transcript(f"turn-{language}", language, 1.0, len(samples) / sample_rate)


class _SyntheticTranslator:
    def __init__(self) -> None:
        self.edges: list[str] = []

    def translate(self, text, edge, context=()):
        self.edges.append(edge.key)
        return f"[{edge.key}] {text}"


class _SyntheticSynthesizer:
    def synthesize(self, text, language):
        return f"{language}:{text}"


class _SyntheticCapture:
    def __init__(self) -> None:
        self.running = False

    def start(self) -> None:
        self.running = True

    def stop(self) -> None:
        self.running = False


def _synthetic_endpoints() -> dict[EndpointRole, AudioEndpointRef]:
    capture = {EndpointRole.LOCAL_MICROPHONE, EndpointRole.CALL_SPEAKER_CAPTURE}
    return {
        role: AudioEndpointRef(
            f"synthetic-{index}",
            f"Synthetic {role.value}",
            EndpointFlow.CAPTURE if role in capture else EndpointFlow.RENDER,
            "synthetic",
            index,
        )
        for index, role in enumerate(EndpointRole)
    }


def _synthetic_catalog(
    root: Path, session: SessionPair, registry: LanguageRegistry
) -> CapabilityCatalog:
    """Every row-7 model present on disk under ``root`` (status ``installed``)."""
    lanes = CallBridgeLanes.from_session(session)
    stt = root / "models" / "stt"
    stt.mkdir(parents=True)
    (stt / "model.bin").write_bytes(b"stt")
    translation = {}
    for edge in (lanes.outbound, lanes.inbound):
        directory = root / "models" / f"mt-{edge.source}-{edge.target}"
        directory.mkdir(parents=True)
        (directory / "model.bin").write_bytes(edge.key.encode())
        translation[edge] = directory
    voices = {}
    for language in (lanes.local, lanes.remote):
        voice = root / "models" / "voices" / f"{language}.onnx"
        voice.parent.mkdir(parents=True, exist_ok=True)
        voice.write_bytes(b"voice")
        voices[language] = voice
    return CapabilityCatalog(
        registry,
        ReadinessProbe(root),
        recognition={language: stt for language in session.pair.members},
        translation=translation,
        voices=voices,
    )


def _synthetic_bridge(session, catalog, outputs, translator):
    lanes = CallBridgeLanes.from_session(session)
    scheduler = InferenceScheduler(max_concurrent=2)
    lane_by_id = {
        lane_id: TranslationLane(
            lane_id,
            lanes.edge(lane_id),
            _SyntheticRecognizer(),
            translator,
            _SyntheticSynthesizer(),
            outputs[lane_id].append,
            scheduler,
        )
        for lane_id in LaneId
    }
    controller = FullDuplexBridgeController(
        _synthetic_endpoints(),
        lane_by_id[LaneId.OUTBOUND],
        lane_by_id[LaneId.INBOUND],
        _SyntheticCapture(),
        _SyntheticCapture(),
        session=session,
        catalog=catalog,
    )
    return controller, lane_by_id


def run_synthetic(config: AppConfig, registry: LanguageRegistry = BUILTIN_REGISTRY) -> int:
    session = call_bridge_session(config, registry)
    lanes = CallBridgeLanes.from_session(session)
    audio = AudioUtterance(np.zeros(1_600, dtype=np.float32), 16_000)
    passed = True
    with tempfile.TemporaryDirectory(prefix="lianiq-call-bridge-") as directory:
        catalog = _synthetic_catalog(Path(directory), session, registry)

        # Case 1: lanes are local>remote and remote>local for the whole session.
        outputs = {lane_id: [] for lane_id in LaneId}
        translator = _SyntheticTranslator()
        controller, lane_by_id = _synthetic_bridge(session, catalog, outputs, translator)
        controller.start()
        for _ in range(2):
            for lane in lane_by_id.values():
                lane.submit(audio)
                lane.wait_until_idle(WAIT_TIMEOUT_SECONDS)
        stopped = controller.stop(timeout=5.0)
        expected = {LaneId.OUTBOUND: lanes.outbound, LaneId.INBOUND: lanes.inbound}
        lanes_passed = stopped and all(
            lane_by_id[lane_id].edge == edge
            and len(outputs[lane_id]) == 2
            and all(output.startswith(f"{edge.target}:[{edge.key}]") for output in outputs[lane_id])
            for lane_id, edge in expected.items()
        )
        passed = passed and lanes_passed
        print(
            f"{'PASS' if lanes_passed else 'FAIL'} lanes: "
            f"outbound={lane_by_id[LaneId.OUTBOUND].edge.key} "
            f"inbound={lane_by_id[LaneId.INBOUND].edge.key} edges_used={sorted(set(translator.edges))}"
        )

        # Case 2: a missing lane voice fails closed before any lane starts and is named.
        catalog.voice_paths()[lanes.remote].unlink()
        outputs = {lane_id: [] for lane_id in LaneId}
        controller, lane_by_id = _synthetic_bridge(
            session, catalog, outputs, _SyntheticTranslator()
        )
        expected_name = describe_voice(lanes.remote, registry)
        try:
            controller.start()
        except ModeUnavailableError as exc:
            names = [describe(item, registry) for item in exc.missing]
            fail_closed = (
                names == [expected_name]
                and not any(lane.running for lane in lane_by_id.values())
                and controller.state is BridgeState.STOPPED
            )
            detail = ", ".join(names)
        else:
            controller.stop(timeout=5.0)
            fail_closed = False
            detail = "the bridge started"
        passed = passed and fail_closed
        print(f"{'PASS' if fail_closed else 'FAIL'} fail-closed: missing {detail}")
    return 0 if passed else 1


def describe_voice(language: LanguageId, registry: LanguageRegistry) -> str:
    return describe(Requirement(RequirementKind.VOICE, language), registry)


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--synthetic",
        action="store_true",
        help="use synthetic adapters and endpoints instead of the offline models",
    )
    args = parser.parse_args(argv)
    config = AppConfig.load()
    return run_synthetic(config) if args.synthetic else run_models(config)


if __name__ == "__main__":
    raise SystemExit(main())
