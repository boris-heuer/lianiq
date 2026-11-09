"""Requirement-scoped adapter construction and warm-up (CAP-0169 AC-05, AC-20, E-08).

The real adapter classes in ``lianiq.app`` are replaced by spy adapters that record every
construction and warm-up, so the tests show which models a started mode would load. The
spy adapters and the window builder are in ``tests/_spy_window.py``; the AC-20 window tests
are in ``test_requirement_scoped_loading_window.py``.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from lianiq.app import build_pipeline
from lianiq.languages import (
    BUILTIN_REGISTRY,
    CapabilityMissingError,
    DeviceReadiness,
    InputKind,
    OutputKind,
    ReadinessProbe,
    ReadinessStatus,
    RoutingKind,
    check,
    describe,
)
from tests._spy_window import (
    DE,
    PAIR_EDGE,
    ZH,
    config_without_stt_and_voices,
    model_dir,
    session,
)
from tests._spy_window import spies as spy_adapters_fixture  # noqa: F401


def test_build_pipeline_builds_registry_catalog_and_no_adapter(tmp_path, spies) -> None:
    config = config_without_stt_and_voices(tmp_path)
    pipeline = build_pipeline(config, probe=ReadinessProbe(tmp_path))

    assert spies.constructed == []
    assert pipeline.registry is BUILTIN_REGISTRY
    assert pipeline.catalog.recognition(DE).status is ReadinessStatus.MISSING
    assert pipeline.catalog.voice(ZH).status is ReadinessStatus.MISSING
    assert pipeline.catalog.translation(PAIR_EDGE).status is ReadinessStatus.INSTALLED


def test_ac05_typed_fixed_text_translates_without_recogniser_or_synthesiser(
    tmp_path, spies
) -> None:
    pipeline = build_pipeline(
        config_without_stt_and_voices(tmp_path), probe=ReadinessProbe(tmp_path)
    )
    typed = session(InputKind.TYPED, RoutingKind.FIXED, OutputKind.TEXT, fixed_source=DE)
    assert check(typed, pipeline.catalog, DeviceReadiness()).available

    pipeline.prepare(typed)
    result = pipeline.translate_text("Guten Tag", typed)

    assert result is not None
    assert result.translated_text == "[de>zh-Hans] Guten Tag"
    assert (result.source_language, result.target_language) == (DE, ZH)
    assert spies.constructed == ["translator"]
    assert spies.translator.warmed_edges == ["de>zh-Hans"]  # one MT model
    assert spies.translator.calls == [("Guten Tag", "de>zh-Hans", ())]
    assert spies.recognizer is None
    assert spies.synthesizer is None


def test_typed_spoken_adds_only_the_target_voice(tmp_path, spies) -> None:
    pipeline = build_pipeline(
        config_without_stt_and_voices(tmp_path), probe=ReadinessProbe(tmp_path)
    )

    pipeline.prepare(session(InputKind.TYPED, RoutingKind.FIXED, OutputKind.SPOKEN, ZH))

    assert spies.constructed == ["translator", "synthesizer"]
    assert spies.translator.warmed_edges == ["zh-Hans>de"]
    assert spies.synthesizer.warmed_languages == ["de"]
    assert spies.recognizer is None


def test_e08_missing_reverse_edge_blocks_automatic_and_fixed_direction_loads_only_its_needs(
    tmp_path, spies
) -> None:
    config = config_without_stt_and_voices(tmp_path, reverse_edge=False)
    config.speech_to_text.model_path = str(model_dir(tmp_path, "faster-whisper-small"))
    pipeline = build_pipeline(config, probe=ReadinessProbe(tmp_path))
    automatic = session(InputKind.MICROPHONE, RoutingKind.BIDIRECTIONAL, OutputKind.TEXT)
    fixed = session(InputKind.MICROPHONE, RoutingKind.FIXED, OutputKind.TEXT, fixed_source=DE)
    devices = DeviceReadiness(microphone=True)

    availability = check(automatic, pipeline.catalog, devices)
    assert not availability.available
    assert [describe(item, BUILTIN_REGISTRY) for item in availability.missing] == [
        "translation Mandarin (Simplified) → German"
    ]
    assert check(fixed, pipeline.catalog, devices).available

    pipeline.prepare(fixed)

    assert spies.constructed == ["recognizer", "translator"]
    assert spies.recognizer.warmed_languages == ["de"]  # no zh-Hans recognition warm-up
    assert spies.translator.warmed_edges == ["de>zh-Hans"]  # reverse edge never assumed
    assert spies.synthesizer is None


def test_text_mode_never_synthesizes_even_if_voice_output_was_saved_on(tmp_path, spies) -> None:
    config = config_without_stt_and_voices(tmp_path)
    config.voice_output = True
    pipeline = build_pipeline(config, probe=ReadinessProbe(tmp_path))
    typed = session(InputKind.TYPED, RoutingKind.FIXED, OutputKind.TEXT, fixed_source=DE)

    pipeline.prepare(typed)
    pipeline.translate_text("Guten Tag", typed)

    assert pipeline.voice_output is False
    assert spies.synthesizer is None
    assert spies.constructed == ["translator"]


def test_adapters_are_constructed_once_across_sessions(tmp_path, spies) -> None:
    pipeline = build_pipeline(
        config_without_stt_and_voices(tmp_path), probe=ReadinessProbe(tmp_path)
    )

    pipeline.prepare(session(InputKind.TYPED, RoutingKind.FIXED, OutputKind.TEXT, DE))
    pipeline.prepare(session(InputKind.TYPED, RoutingKind.FIXED, OutputKind.TEXT, ZH))

    assert spies.constructed == ["translator"]
    assert spies.translator.warmed_edges == ["de>zh-Hans", "zh-Hans>de"]


def test_real_marian_adapter_refuses_an_unconfigured_edge(tmp_path) -> None:
    config = config_without_stt_and_voices(tmp_path)
    config.translation.edges = {"de>zh-Hans": config.translation.edges["de>zh-Hans"]}
    pipeline = build_pipeline(config, probe=ReadinessProbe(tmp_path))
    pipeline.translator = None
    translator = pipeline.text_translator()

    with pytest.raises(CapabilityMissingError, match="zh-Hans>de"):
        translator.translate("你好", PAIR_EDGE.reversed())
