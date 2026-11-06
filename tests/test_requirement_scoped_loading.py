"""Requirement-scoped adapter construction and warm-up (CAP-0169 AC-05, AC-20, E-08).

The real adapter classes in ``lianiq.app`` are replaced by spy adapters that record every
construction and warm-up, so the tests show which models a started mode would load.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import lianiq.app as app_module
from lianiq.app import build_pipeline
from lianiq.config import AppConfig, TranslationEdgeConfig
from lianiq.languages import (
    BUILTIN_REGISTRY,
    CapabilityMissingError,
    DeviceReadiness,
    DirectedEdge,
    InputKind,
    LanguageId,
    OutputKind,
    ReadinessProbe,
    ReadinessStatus,
    RoutingKind,
    SessionPair,
    UsageMode,
    check,
    describe,
)
from tests.languages.synthetic import SpyRecognizer, SpySynthesizer, SpyTranslator

DE = LanguageId("de")
ZH = LanguageId("zh-Hans")
PAIR = BUILTIN_REGISTRY.pair(DE, ZH)
PAIR_EDGE = DirectedEdge(DE, ZH)


@dataclass
class SpyAdapters:
    constructed: list[str] = field(default_factory=list)
    recognizer: SpyRecognizer | None = None
    translator: SpyTranslator | None = None
    synthesizer: SpySynthesizer | None = None
    translator_edges: dict = field(default_factory=dict)
    voices: dict = field(default_factory=dict)
    # Translator warm-up blocks until released, so tests can act while models load.
    release_warm_up: threading.Event = field(default_factory=threading.Event)
    failing_warm_up_calls: set[int] = field(default_factory=set)


class GatedSpyTranslator(SpyTranslator):
    def __init__(self, adapters: SpyAdapters) -> None:
        super().__init__()
        self.adapters = adapters
        self.warm_up_calls = 0

    def warm_up(self, edges) -> None:
        self.warm_up_calls += 1
        assert self.adapters.release_warm_up.wait(timeout=5.0)
        if self.warm_up_calls in self.adapters.failing_warm_up_calls:
            raise RuntimeError(f"warm-up {self.warm_up_calls} failed")
        super().warm_up(edges)


@pytest.fixture
def spies(monkeypatch) -> SpyAdapters:
    adapters = SpyAdapters()
    adapters.release_warm_up.set()

    def recognizer(_config, _model_path, _registry):
        adapters.constructed.append("recognizer")
        adapters.recognizer = SpyRecognizer()
        return adapters.recognizer

    def translator(edges, _glossary, **_options):
        adapters.constructed.append("translator")
        adapters.translator_edges = dict(edges)
        adapters.translator = GatedSpyTranslator(adapters)
        return adapters.translator

    def synthesizer(voices, **_options):
        adapters.constructed.append("synthesizer")
        adapters.voices = dict(voices)
        adapters.synthesizer = SpySynthesizer()
        return adapters.synthesizer

    monkeypatch.setattr(app_module, "FasterWhisperEngine", recognizer)
    monkeypatch.setattr(app_module, "MarianTranslator", translator)
    monkeypatch.setattr(app_module, "PiperEngine", synthesizer)
    return adapters


def model_dir(root: Path, name: str) -> Path:
    path = root / "models" / name
    path.mkdir(parents=True)
    (path / "model.bin").write_bytes(name.encode())
    return path


def config_without_stt_and_voices(root: Path, *, reverse_edge: bool = True) -> AppConfig:
    """Only translation models are on disk; STT model and voices are configured but absent."""
    config = AppConfig()
    config.speech_to_text.model_path = str(root / "models" / "faster-whisper-small")
    config.tts.voices = {
        "de": str(root / "models" / "piper" / "de.onnx"),
        "zh-Hans": str(root / "models" / "piper" / "zh.onnx"),
    }
    config.tts.engines = {}  # both test voices are Piper files
    config.translation.edges = {
        "de>zh-Hans": TranslationEdgeConfig(str(model_dir(root, "opus-mt-de-zh"))),
        # E-08 data D-05: the reverse edge stays configured but its folder is renamed.
        "zh-Hans>de": TranslationEdgeConfig(
            str(model_dir(root, "opus-mt-zh-de") if reverse_edge else root / "models" / "off")
        ),
    }
    config.translation.glossary_path = str(root / "glossary.json")
    return config


def provision_stt_and_voices(root: Path, config: AppConfig) -> None:
    """Put the STT model and both voices on disk so the session start gate passes."""
    config.speech_to_text.model_path = str(model_dir(root, "faster-whisper-small"))
    for voice in config.tts.voices.values():
        Path(voice).parent.mkdir(parents=True, exist_ok=True)
        Path(voice).write_bytes(b"voice")


def session(input_kind, routing, output, fixed_source=None) -> SessionPair:
    return SessionPair(PAIR, UsageMode(input_kind, routing, output), fixed_source=fixed_source)


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


def build_window(tmp_path: Path, monkeypatch, *, provisioned: bool = True, configure=None):
    """A shown MainWindow over spy adapters; ``provisioned`` puts STT and voices on disk.

    ``configure(config, root)`` adjusts the settings and files before the catalog is built.
    """
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    import lianiq.ui.main_window as main_window_module
    from lianiq.audio.devices import AudioDevice
    from lianiq.audio.endpoints import EndpointInventory

    QApplication.instance() or QApplication([])
    # One microphone and one speaker, so the device requirements of every mode are met.
    devices = [AudioDevice(0, "Test microphone", 1, 0), AudioDevice(1, "Test speakers", 0, 2)]
    monkeypatch.setattr(main_window_module, "list_audio_devices", lambda: list(devices))
    monkeypatch.setattr(main_window_module, "list_audio_endpoints", lambda: EndpointInventory([]))
    capture = main_window_module.MicrophoneCapture
    monkeypatch.setattr(capture, "start", lambda self: setattr(self, "_stream", object()))
    monkeypatch.setattr(capture, "stop", lambda self: setattr(self, "_stream", None))
    config = config_without_stt_and_voices(tmp_path)
    if provisioned:
        provision_stt_and_voices(tmp_path, config)
    if configure is not None:
        configure(config, tmp_path)
    pipeline = build_pipeline(config, probe=ReadinessProbe(tmp_path))
    window = main_window_module.MainWindow(config, pipeline, persist_settings=False)
    window.show()
    return window


class TestMainWindowLoadsOnlyOnStart:
    """AC-20: no model loads before Start; Start loads only mode-required adapters."""

    @pytest.fixture
    def window(self, tmp_path, spies, monkeypatch):
        window = build_window(tmp_path, monkeypatch)
        yield window
        window.close()

    @staticmethod
    def wait_until(condition, timeout_ms: int = 3_000) -> bool:
        from PySide6.QtTest import QTest

        waited = 0
        while not condition() and waited < timeout_ms:
            QTest.qWait(10)
            waited += 10
        return condition()

    @pytest.mark.parametrize(
        ("mode_label", "spoken", "recognition", "edges", "voices"),
        [
            (
                "Automatic (German ↔ Mandarin (Simplified))",
                False,
                ["de", "zh-Hans"],
                ["de>zh-Hans", "zh-Hans>de"],
                None,
            ),
            ("German → Mandarin (Simplified)", False, ["de"], ["de>zh-Hans"], None),
            ("Mandarin (Simplified) → German", True, ["zh-Hans"], ["zh-Hans>de"], ["de"]),
        ],
    )
    def test_ac20_start_warms_only_the_started_modes_requirements(
        self, window, spies, mode_label, spoken, recognition, edges, voices
    ) -> None:
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest

        QTest.qWait(50)
        assert spies.constructed == []  # nothing constructed or loaded before Start
        assert window.start_button.isEnabled()

        window.mode_combo.setCurrentText(mode_label)
        window.tts_checkbox.setChecked(spoken)
        assert spies.constructed == []
        QTest.mouseClick(window.start_button, Qt.MouseButton.LeftButton)

        assert self.wait_until(lambda: window.capture.running)
        assert spies.recognizer.warmed_languages == recognition
        assert spies.translator.warmed_edges == edges
        if voices is None:
            assert spies.synthesizer is None
            assert spies.constructed == ["recognizer", "translator"]
        else:
            assert spies.synthesizer.warmed_languages == voices
        window.stop_listening()

    @pytest.mark.parametrize("spoken", [False, True])
    def test_voice_output_is_bound_at_start_and_locked_while_models_load(
        self, window, spies, spoken
    ) -> None:
        # CAP-0169 AC-13 (WI-04 review F6): Voice output is part of the session bound at
        # Start; it is disabled while the models load and while the session runs.
        window.mode_combo.setCurrentText("German → Mandarin (Simplified)")
        window.tts_checkbox.setChecked(spoken)
        spies.release_warm_up.clear()
        window.start_listening()
        assert not window.tts_checkbox.isEnabled()
        assert window.tts_checkbox.toolTip() == "Stop the session to change language pair or mode"
        window.tts_checkbox.setChecked(not spoken)  # a programmatic toggle changes nothing
        spies.release_warm_up.set()

        assert self.wait_until(lambda: window.capture.running)
        assert window.pipeline.voice_output is spoken
        expected = OutputKind.SPOKEN if spoken else OutputKind.TEXT
        assert window.session_controller.session.mode.output is expected
        assert not window.tts_checkbox.isEnabled()
        window.stop_listening()
        assert window.tts_checkbox.isEnabled()

    def test_a_stopped_start_never_starts_capture_for_the_next_start(self, window, spies) -> None:
        spies.failing_warm_up_calls = {2}
        spies.release_warm_up.clear()
        window.start_listening()  # Start A; its warm-up blocks
        assert self.wait_until(lambda: spies.translator is not None)
        window.stop_listening()
        window.mode_combo.setCurrentText("German → Mandarin (Simplified)")
        window.start_listening()  # Start B; its warm-up fails
        spies.release_warm_up.set()

        assert self.wait_until(lambda: window.state_label.text() == "Model error")
        assert window.statusBar().currentMessage() == "warm-up 2 failed"
        assert not window.capture.running
        assert window.start_button.isEnabled()
