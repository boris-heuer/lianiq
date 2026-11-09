"""The ``SessionController`` harness shared by ``test_session*.py`` (CAP-0169 AC-14, AC-15)."""

from __future__ import annotations

import threading

import numpy as np

from lianiq.conversation.routing import HeldTurn
from lianiq.domain import AudioUtterance, Transcript, TranslationResult
from lianiq.languages import (
    BUILTIN_LANGUAGES,
    DeviceReadiness,
    InputKind,
    LanguageId,
    LanguageRegistry,
    OutputKind,
    RoutingKind,
    SessionController,
    SessionPair,
    UsageMode,
)
from lianiq.pipeline import PipelineRunner, TranslationPipeline
from tests.languages.synthetic import QAA, QAB, SYNTHETIC_LANGUAGES, provisioned_catalog

DE = LanguageId("de")
ZH = LanguageId("zh-Hans")
REGISTRY = LanguageRegistry(BUILTIN_LANGUAGES + SYNTHETIC_LANGUAGES)
DE_ZH = REGISTRY.pair(DE, ZH)
QAA_QAB = REGISTRY.pair(QAA, QAB)
MICROPHONE_TEXT = UsageMode(InputKind.MICROPHONE, RoutingKind.BIDIRECTIONAL, OutputKind.TEXT)
AUTOMATIC = SessionPair(DE_ZH, MICROPHONE_TEXT)
ALL_EDGES = ("de>zh-Hans", "zh-Hans>de", "qaa>qab", "qab>qaa")
AUDIO = AudioUtterance(np.zeros(1_600, dtype=np.float32), 16_000)


def fixed(source: LanguageId, output: OutputKind = OutputKind.TEXT) -> SessionPair:
    mode = UsageMode(InputKind.MICROPHONE, RoutingKind.FIXED, output)
    return SessionPair(DE_ZH, mode, fixed_source=source)


class ScriptedRecognizer:
    """Returns scripted (language, text) transcripts; the first call can block."""

    def __init__(self, script, gate: threading.Event | None = None) -> None:
        self.script = list(script)
        self.gate = gate
        self.started = threading.Event()
        self.calls: list[str | None] = []

    def transcribe(self, samples, sample_rate, language=None):
        self.calls.append(language)
        self.started.set()
        if self.gate is not None:
            assert self.gate.wait(timeout=5.0)
        detected, text = self.script.pop(0)
        return Transcript(text, LanguageId(detected), 0.99, 0.1, detected)


class TaggingTranslator:
    def __init__(self) -> None:
        self.calls = []

    def translate(self, text, edge, context=()):
        self.calls.append((text, edge.key, tuple(context)))
        return f"[{edge.key}] {text}"


class RecordingCapture:
    def __init__(self, events: list[str], fail: bool = False) -> None:
        self.events = events
        self.fail = fail

    def start(self) -> None:
        self.events.append("capture.start")
        if self.fail:
            raise RuntimeError("no microphone")

    def stop(self) -> None:
        self.events.append("capture.stop")


class Harness:
    def __init__(self, tmp_path, recognizer, *, voices=(), capture_fails=False) -> None:
        self.events: list[str] = []
        self.results: list[TranslationResult] = []
        self.held: list[HeldTurn] = []
        self.errors: list[str] = []
        catalog = provisioned_catalog(
            tmp_path,
            REGISTRY,
            recognition=(DE, ZH, QAA, QAB),
            edges=ALL_EDGES,
            voices=voices,
        )
        self.translator = TaggingTranslator()
        self.pipeline = TranslationPipeline(
            recognizer, self.translator, None, None, registry=REGISTRY, catalog=catalog
        )
        self.runner = PipelineRunner(
            self.pipeline,
            on_result=self.results.append,
            on_error=self.errors.append,
            on_held=self.held.append,
        )
        self.capture = RecordingCapture(self.events, fail=capture_fails)
        self.controller = SessionController(
            self.pipeline,
            self.runner,
            devices=lambda: DeviceReadiness(microphone=True, playback=False),
            capture=self.capture,
        )

    def context_is_empty(self) -> bool:
        return all(self.pipeline.context.source_context(lang) == () for lang in (DE, ZH, QAA))
