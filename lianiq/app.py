from __future__ import annotations

import logging
import os
import sys

from lianiq.audio.playback import play_wav
from lianiq.config import PROJECT_ROOT, AppConfig
from lianiq.config_migration import SettingsMigrationError
from lianiq.conversation.routing import TurnRouter
from lianiq.languages.capabilities import CapabilityCatalog, ReadinessProbe
from lianiq.languages.registry import BUILTIN_REGISTRY, LanguageRegistry
from lianiq.logging_setup import configure_logging
from lianiq.pipeline import AdapterFactories, TranslationPipeline
from lianiq.stt.faster_whisper_engine import FasterWhisperEngine
from lianiq.translation.glossary import Glossary
from lianiq.translation.marian_engine import MarianTranslator
from lianiq.tts.piper_engine import PiperEngine


def build_pipeline(
    config: AppConfig,
    registry: LanguageRegistry = BUILTIN_REGISTRY,
    probe: ReadinessProbe | None = None,
) -> TranslationPipeline:
    """Build the registry-backed catalog and a pipeline whose adapters are not yet built.

    No adapter is constructed and no model is loaded here; ``TranslationPipeline.prepare``
    constructs and warms only what the started mode's requirement set names.
    """
    catalog = CapabilityCatalog.from_config(config, registry, probe or ReadinessProbe(PROJECT_ROOT))

    def recognizer() -> FasterWhisperEngine:
        return FasterWhisperEngine(
            config.speech_to_text,
            AppConfig.resolve(config.speech_to_text.model_path),
            registry,
        )

    def translator() -> MarianTranslator:
        return MarianTranslator(
            catalog.translation_paths(),
            Glossary(AppConfig.resolve(config.translation.glossary_path)),
            cpu_threads=config.translation.cpu_threads,
            device=config.translation.device,
        )

    def synthesizer() -> PiperEngine:
        return PiperEngine(
            catalog.voice_paths(),
            length_scale=config.tts.length_scale,
            device=config.tts.device,
            registry=registry,
        )

    pipeline = TranslationPipeline(
        playback=play_wav,
        context_sentences=config.translation.context_sentences,
        output_device=config.audio.output_device,
        turn_router=TurnRouter(config.languages.detection_min_probability),
        factories=AdapterFactories(recognizer, translator, synthesizer),
        registry=registry,
        catalog=catalog,
    )
    pipeline.set_voice_output(config.voice_output)
    return pipeline


def report_settings_error(error: SettingsMigrationError) -> None:
    """Show why settings could not be loaded; no settings file is written."""
    message = (
        f"{error}.\n\nLianiq did not change any settings file. Correct or remove this "
        "value in config/settings.local.json and start Lianiq again."
    )
    if sys.stderr is not None:
        print(message, file=sys.stderr)
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox
    except ImportError:
        return
    # The dialog needs a QApplication; keep the reference alive while it is shown.
    application = QApplication.instance() or QApplication(sys.argv)
    application.setApplicationName("lianiq")
    QMessageBox.critical(None, "lianiq settings", message)


def main() -> int:
    try:
        config = AppConfig.load()
    except SettingsMigrationError as error:
        report_settings_error(error)
        return 2
    configure_logging(PROJECT_ROOT / "logs", config.ui.log_level)
    os.environ.setdefault("QT_OPENGL", "software")
    os.environ.setdefault("QT_QUICK_BACKEND", "software")
    try:
        from PySide6.QtCore import QCoreApplication, Qt
        from PySide6.QtWidgets import QApplication

        from lianiq.ui.main_window import MainWindow
    except ImportError as exc:
        logging.getLogger(__name__).exception("GUI dependency import failed")
        if sys.stderr is not None:
            print(f"GUI dependency is missing: {exc}", file=sys.stderr)
        return 2

    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_UseSoftwareOpenGL)
    application = QApplication(sys.argv)
    application.setApplicationName("lianiq")
    pipeline = build_pipeline(config)
    window = MainWindow(config, pipeline)
    window.show()
    return application.exec()
