"""``scripts/benchmark.py`` selects its session by language ID (CAP-0169 WI-07)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from lianiq.config import AppConfig
from lianiq.languages import (
    BUILTIN_REGISTRY,
    LanguageContractError,
    OutputKind,
    RoutingKind,
    UnsupportedModeError,
)


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
