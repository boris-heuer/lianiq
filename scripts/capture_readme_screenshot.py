from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

os.environ.setdefault("QT_OPENGL", "software")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
os.environ.setdefault("QT_SCALE_FACTOR", "1")

from lianiq.audio.device_inventory import ConversationInventory
from lianiq.audio.endpoints import EndpointInventory
from lianiq.call_bridge.contracts import AudioEndpointRef, EndpointFlow
from lianiq.config import AppConfig
from lianiq.conversation.routing import HeldTurn
from lianiq.domain import Transcript
from lianiq.languages import (
    BUILTIN_REGISTRY,
    CapabilityCatalog,
    LanguageId,
    ReadinessProbe,
    ReadinessStatus,
)
from lianiq.pipeline import TranslationPipeline

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = ROOT / "docs" / "assets" / "application-ui.png"
# Generic, host-independent devices; the public screenshot never enumerates real hardware.
GENERIC_DEVICES = (
    AudioEndpointRef(
        "audio-endpoint:v1:capture:generic", "Microphone", EndpointFlow.CAPTURE, "WASAPI", 0
    ),
    AudioEndpointRef(
        "audio-endpoint:v1:render:generic", "Speakers", EndpointFlow.RENDER, "WASAPI", 1, 2
    ),
)
GENERIC_INVENTORY = ConversationInventory(
    GENERIC_DEVICES,
    {endpoint.flow: endpoint.endpoint_id for endpoint in GENERIC_DEVICES},
    {endpoint.runtime_index: endpoint.display_name for endpoint in GENERIC_DEVICES},
)
CAPTURE_HEIGHT = 800
# A synthetic held turn (spoken language outside the pair) so the held-turn bar is shown.
SAMPLE_HELD_TURN = HeldTurn(
    turn_id=UUID(int=0),
    captured_at=datetime(2026, 1, 1, tzinfo=UTC),
    transcript=Transcript(
        text="Could you repeat the last sentence, please?",
        language=LanguageId("en"),
        probability=0.93,
        duration_seconds=2.4,
        engine_language_code="en",
    ),
    reason="out_of_pair",
)


class _ReadyRecognizer:
    device = "cpu"

    @staticmethod
    def warm_up(_languages=()) -> None:
        return None


class _ReadyTranslator:
    @staticmethod
    def warm_up(_edges=()) -> None:
        return None


class _ReadyProbe(ReadinessProbe):
    """Reports every configured model as installed, so no model files are needed."""

    def probe_file(self, path: Path) -> ReadinessStatus:
        return ReadinessStatus.INSTALLED

    def probe_directory(self, path: Path) -> ReadinessStatus:
        return ReadinessStatus.INSTALLED


def build_screenshot_pipeline(config: AppConfig) -> TranslationPipeline:
    """A pipeline over the default settings whose models report ready but never load."""
    catalog = CapabilityCatalog.from_config(config, BUILTIN_REGISTRY, _ReadyProbe(ROOT))
    return TranslationPipeline(
        _ReadyRecognizer(),
        _ReadyTranslator(),
        synthesizer=None,
        playback=None,
        registry=BUILTIN_REGISTRY,
        catalog=catalog,
    )


def main(argv: list[str] | None = None) -> int:
    from PySide6.QtCore import QCoreApplication, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    import lianiq.ui.device_setup as device_setup_module
    import lianiq.ui.main_window as main_window_module
    import lianiq.ui.workspaces.call_bridge as call_bridge_module

    parser = argparse.ArgumentParser(description="Capture the sanitized README screenshot.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    output = parser.parse_args(argv).output

    patched = {
        (device_setup_module, "read_inventory"): lambda: GENERIC_INVENTORY,
        (device_setup_module, "read_native_ids"): dict,
        (device_setup_module, "reinitialize_portaudio"): lambda: None,
        (call_bridge_module, "list_audio_endpoints"): lambda: EndpointInventory([]),
    }
    original = {target: getattr(*target) for target in patched}
    for (module, name), replacement in patched.items():
        setattr(module, name, replacement)
    try:
        application = QApplication.instance()
        if application is None:
            QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_UseSoftwareOpenGL)
            application = QApplication(sys.argv[:1])
            application.setApplicationName("lianiq screenshot capture")
        config = AppConfig()
        window = main_window_module.MainWindow(
            config, build_screenshot_pipeline(config), persist_settings=False
        )
        # Taller than the default so the held-turn bar does not compress the other rows.
        window.resize(window.width(), max(window.height(), CAPTURE_HEIGHT))
        window.show()
        window.held_turn_bar.set_held(
            [SAMPLE_HELD_TURN], BUILTIN_REGISTRY.pair(*config.languages.pair)
        )
        QTest.qWait(500)
        application.processEvents()

        screenshot = window.grab()
        saved = screenshot.save(str(output), "PNG")
        window.close()
        application.processEvents()
    finally:
        for (module, name), value in original.items():
            setattr(module, name, value)
    if not saved:
        print(f"Could not save screenshot to {output}", file=sys.stderr)
        return 1
    print(f"Saved sanitized {screenshot.width()}x{screenshot.height()} screenshot to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
