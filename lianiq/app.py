from __future__ import annotations

import logging
import os
import sys

from lianiq.audio.playback import play_wav
from lianiq.config import PROJECT_ROOT, AppConfig
from lianiq.logging_setup import configure_logging
from lianiq.pipeline import TranslationPipeline
from lianiq.stt.faster_whisper_engine import FasterWhisperEngine
from lianiq.translation.glossary import Glossary
from lianiq.translation.marian_engine import MarianTranslator
from lianiq.tts.piper_engine import PiperEngine


def build_pipeline(config: AppConfig) -> tuple[TranslationPipeline, PiperEngine]:
    recognizer = FasterWhisperEngine(
        config.speech_to_text,
        AppConfig.resolve(config.speech_to_text.model_path),
    )
    translator = MarianTranslator(
        AppConfig.resolve(config.translation.de_zh_model_path),
        AppConfig.resolve(config.translation.zh_de_model_path),
        Glossary(AppConfig.resolve(config.translation.glossary_path)),
        cpu_threads=config.translation.cpu_threads,
        device=config.translation.device,
    )
    synthesizer = PiperEngine(
        AppConfig.resolve(config.tts.de_voice_path),
        AppConfig.resolve(config.tts.zh_voice_path),
        length_scale=config.tts.length_scale,
        device=config.tts.device,
    )
    pipeline = TranslationPipeline(
        recognizer,
        translator,
        synthesizer if config.tts.enabled else None,
        play_wav,
        context_sentences=config.translation.context_sentences,
        output_device=config.audio.output_device,
    )
    return pipeline, synthesizer


def main() -> int:
    config = AppConfig.load()
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
    pipeline, synthesizer = build_pipeline(config)
    window = MainWindow(config, pipeline)
    window.set_synthesizer_reference(synthesizer)
    window.show()
    return application.exec()
