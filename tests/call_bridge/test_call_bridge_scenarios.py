from __future__ import annotations

import threading

import numpy as np

from offline_translator.call_bridge.contracts import LaneId
from offline_translator.call_bridge.inference_scheduler import InferenceScheduler
from offline_translator.call_bridge.translation_lane import TranslationLane
from offline_translator.domain import AudioUtterance, Language, Transcript


def test_full_duplex_routes_outputs_to_only_their_declared_sinks() -> None:
    barrier = threading.Barrier(2)
    tx_output = []
    rx_output = []

    class Recognizer:
        def transcribe(self, samples, sample_rate, language=None):
            barrier.wait(timeout=1.0)
            return Transcript(language.value, language, 1.0, len(samples) / sample_rate)

    class Translator:
        def translate(self, text, source, target, context=()):
            return target.value

    class Synthesizer:
        def synthesize(self, text, language):
            return text

    scheduler = InferenceScheduler(max_concurrent=2)
    outbound = TranslationLane(
        LaneId.OUTBOUND,
        Language.GERMAN,
        Language.MANDARIN,
        Recognizer(),
        Translator(),
        Synthesizer(),
        tx_output.append,
        scheduler,
    )
    inbound = TranslationLane(
        LaneId.INBOUND,
        Language.MANDARIN,
        Language.GERMAN,
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

    assert tx_output == ["zh"]
    assert rx_output == ["de"]
