"""Spy adapters and the offscreen MainWindow builder shared by the requirement-scoped tests.

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
    DirectedEdge,
    LanguageId,
    ReadinessProbe,
    SessionPair,
    UsageMode,
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


# The explicit name keeps the fixture "spies" when a test module imports it under an alias.
@pytest.fixture(name="spies")
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


def build_window(tmp_path: Path, monkeypatch, *, provisioned: bool = True, configure=None):
    """A shown MainWindow over spy adapters; ``provisioned`` puts STT and voices on disk.

    ``configure(config, root)`` adjusts the settings and files before the catalog is built.
    """
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    import lianiq.ui.main_window as main_window_module
    import lianiq.ui.workspaces.call_bridge as call_bridge_module
    import lianiq.ui.workspaces.conversation as conversation_module
    from lianiq.audio.devices import AudioDevice
    from lianiq.audio.endpoints import EndpointInventory

    QApplication.instance() or QApplication([])
    # One microphone and one speaker, so the device requirements of every mode are met.
    devices = [AudioDevice(0, "Test microphone", 1, 0), AudioDevice(1, "Test speakers", 0, 2)]
    monkeypatch.setattr(conversation_module, "list_audio_devices", lambda: list(devices))
    monkeypatch.setattr(call_bridge_module, "list_audio_endpoints", lambda: EndpointInventory([]))
    capture = conversation_module.MicrophoneCapture
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
