"""Fakes for the CAP-0170 lifecycle tests: capture, microphone, gated adapters."""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from lianiq.listen.controller import ListenController
from lianiq.listen.pipeline import ListenPipeline
from lianiq.listen.session import listen_readiness, listen_session
from lianiq.packs.protection import ActiveUsageTracker
from lianiq.pipeline import AdapterFactories, TranslationPipeline
from lianiq.ui.shell.session_owner import ActiveSessionOwner
from lianiq.ui.shell.workspaces import WorkspaceId
from tests._pipeline_helpers import FakeRecognizer, utterance
from tests.languages.synthetic import provisioned_catalog
from tests.text_translation._text_helpers import DE, ZH, GuiThread, three_language_registry


@dataclass(frozen=True)
class Endpoint:
    runtime_index: int = 3


@dataclass
class Mic:
    ready: bool = True
    label: str = "Headset"
    endpoint: Endpoint | None = field(default_factory=Endpoint)


class FakeCapture:
    def __init__(self, on_utterance, on_error) -> None:
        self.on_utterance, self.on_error = on_utterance, on_error
        self.device: int | None = None
        self.running = False

    def start(self) -> None:
        self.running = True

    def stop(self) -> None:
        self.running = False

    def speak(self) -> None:
        """One segment from the audio callback thread."""
        thread = threading.Thread(target=self.on_utterance, args=(utterance(),))
        thread.start()
        thread.join()


class GatedTranslator:
    def __init__(self, error: BaseException | None = None) -> None:
        self.release = threading.Event()
        self.error = error
        self.calls = 0
        self.finished = threading.Event()

    def translate(self, text, edge, context=()):
        self.calls += 1
        assert self.release.wait(5.0)
        self.finished.set()
        if self.error is not None:
            raise self.error
        return "早上好"


class Harness:
    def __init__(self, tmp_path: Path, translator=None, recognizer=None, **timing) -> None:
        registry = three_language_registry()
        self.catalog = provisioned_catalog(
            tmp_path, registry, recognition=["de"], edges=["de>zh-Hans"]
        )
        self.synthesized: list[str] = []
        shared = TranslationPipeline(
            recognizer or FakeRecognizer(text="Guten Morgen"),
            translator or GatedTranslator(),
            catalog=self.catalog,
            factories=AdapterFactories(synthesizer=lambda: self.synthesized.append("built")),
        )
        self.pipeline = ListenPipeline(shared)
        self.owner = ActiveSessionOwner()
        self.tracker = ActiveUsageTracker(self.owner)
        self.mic = Mic()
        self.gui = GuiThread()
        self.captures: list[FakeCapture] = []
        self.snapshots: list = []
        self.alerts: list = []
        self.session = listen_session(registry.pair(DE, ZH), DE)
        self.controller = ListenController(
            self.owner,
            self.tracker,
            self.pipeline,
            self._capture,
            lambda: self.mic,
            self.gui.post,
            self.snapshots.append,
            self.alerts.append,
            lambda session: listen_readiness(
                session, self.catalog, None, self.mic, self.owner.busy_for(WorkspaceId.LISTEN)
            ),
            **timing,
        )

    def _capture(self, **callbacks) -> FakeCapture:
        capture = FakeCapture(**callbacks)
        self.captures.append(capture)
        return capture

    def pump(self, until) -> None:
        self.gui.pump(until)

    def drain(self, seconds: float) -> None:
        """Run every callback posted within ``seconds``."""
        deadline = time.monotonic() + seconds
        while (remaining := deadline - time.monotonic()) > 0:
            try:
                self.gui._queue.get(timeout=remaining)()
            except queue.Empty:
                return

    def states(self) -> list:
        return [row.state for row in self.controller.transcript.rows]
