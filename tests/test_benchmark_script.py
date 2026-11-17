"""``scripts/benchmark.py`` selects its session by language ID (CAP-0169 WI-07)."""

from __future__ import annotations

import importlib.util
import sys
import wave
from pathlib import Path

import numpy as np
import pytest

from lianiq.config import AppConfig
from lianiq.languages import (
    BUILTIN_REGISTRY,
    LanguageContractError,
    OutputKind,
    RoutingKind,
    UnsupportedModeError,
)
from tests.languages.synthetic import SpyTranslator
from tests.meeting.support import AUDIO, DE, ZH, Line, PcmSynthesizer, ScriptedRecognizer


def load_benchmark_module():
    script = Path(__file__).parents[1] / "scripts" / "benchmark.py"
    spec = importlib.util.spec_from_file_location("benchmark", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_without_source_the_benchmark_detects_within_the_configured_pair() -> None:
    session = load_benchmark_module().benchmark_session(BUILTIN_REGISTRY, AppConfig(), None)

    assert session.pair.members == ("de", "zh-Hans")
    assert session.mode.routing is RoutingKind.BIDIRECTIONAL
    assert session.fixed_source is None
    assert session.mode.output is OutputKind.TEXT


@pytest.mark.parametrize(("source", "target"), [("de", "zh-Hans"), ("zh-hans", "de")])
def test_a_source_language_id_fixes_the_direction(source, target) -> None:
    config = AppConfig()
    config.voice_output = True

    session = load_benchmark_module().benchmark_session(BUILTIN_REGISTRY, config, source)

    assert session.mode.routing is RoutingKind.FIXED
    assert session.fixed_target == target
    assert session.mode.output is OutputKind.SPOKEN


@pytest.mark.parametrize("source", ["en", "xx"])
def test_a_source_outside_the_pair_is_rejected(source) -> None:
    with pytest.raises((LanguageContractError, UnsupportedModeError, ValueError)):
        load_benchmark_module().benchmark_session(BUILTIN_REGISTRY, AppConfig(), source)


def write_fixture(path: Path, tag: int, seconds: float = 0.3) -> Path:
    """A 16 kHz PCM16 "recording" whose amplitude encodes ``tag`` for the spy recogniser."""
    samples = np.full(round(16_000 * seconds), 0.05 + tag / 1000, dtype=np.float32)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16_000)
        wav.writeframes((samples * 32767).astype(np.int16).tobytes())
    return path


def test_the_meeting_run_reports_the_median_pause_to_text_of_both_inputs(tmp_path) -> None:
    """CAP-0177 spec §9 item 8: a two-input meeting run on fixtures passed by path.

    Synthetic dry run: spy engines and generated fixtures stand in for the models and the
    recordings, which stay outside the repository.
    """
    module = load_benchmark_module()
    session = module.meeting_session(BUILTIN_REGISTRY, AppConfig())
    script = {10: Line(ZH, "你好"), 11: Line(ZH, "谢谢"), 20: Line(DE, "Guten Tag")}
    engines = module.SharedEngines(ScriptedRecognizer(script), SpyTranslator(), PcmSynthesizer())
    table = [write_fixture(tmp_path / "t1.wav", 10), write_fixture(tmp_path / "t2.wav", 11)]
    user = [write_fixture(tmp_path / "u1.wav", 20)]

    latencies = module.run_meeting(session, engines, table, user, AUDIO, realtime=False)
    lines, median = module.meeting_report(latencies)

    assert {role: len(values) for role, values in latencies.items()} == {
        "table_capture": 2,
        "user_capture": 1,
    }
    assert median is not None and 0 <= median < module.MEETING_TARGET_SECONDS
    assert lines[-1].startswith("Median pause-to-text:") and "over 3 lines" in lines[-1]
    assert len(engines.synthesizer.calls) == 1  # the PO's speech, synthesised in memory
