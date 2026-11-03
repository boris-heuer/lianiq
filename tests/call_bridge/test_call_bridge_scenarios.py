from __future__ import annotations

import threading

import numpy as np

from lianiq.call_bridge.contracts import LaneId
from lianiq.call_bridge.inference_scheduler import InferenceScheduler
from lianiq.call_bridge.translation_lane import TranslationLane
from lianiq.domain import AudioUtterance, Transcript
from lianiq.languages.registry import LanguageId

GERMAN = LanguageId("de")
MANDARIN = LanguageId("zh-Hans")


def test_full_duplex_routes_outputs_to_only_their_declared_sinks() -> None:
    barrier = threading.Barrier(2)
    tx_output = []
    rx_output = []

    class Recognizer:
        def transcribe(self, samples, sample_rate, language=None):
            barrier.wait(timeout=1.0)
            return Transcript(language, language, 1.0, len(samples) / sample_rate)

    class Translator:
        def translate(self, text, edge, context=()):
            return edge.key

    class Synthesizer:
        def synthesize(self, text, language):
            return text

    scheduler = InferenceScheduler(max_concurrent=2)
    outbound = TranslationLane(
        LaneId.OUTBOUND,
        GERMAN,
        MANDARIN,
        Recognizer(),
        Translator(),
        Synthesizer(),
        tx_output.append,
        scheduler,
    )
    inbound = TranslationLane(
        LaneId.INBOUND,
        MANDARIN,
        GERMAN,
        Recognizer(),
        Translator(),
        Synthesizer(),
        rx_output.append,
        scheduler,
    )
    outbound.start()
    inbound.start()
    audio = AudioUtterance(np.zeros(160, dtype=np.float32), 16_000)

    outbound.submit(audio)
    inbound.submit(audio)
    assert outbound.wait_until_idle(1.0)
    assert inbound.wait_until_idle(1.0)
    outbound.stop(1.0)
    inbound.stop(1.0)

    assert tx_output == ["de>zh-Hans"]
    assert rx_output == ["zh-Hans>de"]
