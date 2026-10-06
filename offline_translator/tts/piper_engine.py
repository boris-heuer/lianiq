from __future__ import annotations

import tempfile
import wave
from pathlib import Path

from offline_translator.domain import Language
from offline_translator.hardware import resolve_onnx_device


class PiperEngine:
    """Keeps both Piper voices cached to avoid process and model-load latency."""

    def __init__(
        self,
        de_voice_path: Path,
        zh_voice_path: Path,
        length_scale: float = 1.0,
        device: str = "auto",
    ) -> None:
        self.voices = {
            Language.GERMAN: de_voice_path,
            Language.MANDARIN: zh_voice_path,
        }
        self.length_scale = length_scale
        self.device = resolve_onnx_device(device)
        self._loaded: dict[Language, object] = {}

    def validate_voice_files(
        self, languages: tuple[Language, ...] = (Language.GERMAN, Language.MANDARIN)
    ) -> None:
        missing: list[Path] = []
        for language in languages:
            voice_path = self.voices[language]
            for required in (voice_path, Path(f"{voice_path}.json")):
                if not required.is_file():
                    missing.append(required)
        if missing:
            paths = ", ".join(str(path) for path in missing)
            raise FileNotFoundError(
                "Piper voice artifacts are missing: "
                f"{paths}. Provision license-reviewed voice and metadata files first."
            )

    def _load(self, language: Language):
        if language in self._loaded:
            return self._loaded[language]
        voice_path = self.voices[language]
        self.validate_voice_files((language,))
        try:
            from piper import PiperVoice
        except ImportError as exc:
            raise RuntimeError("piper-tts is not installed") from exc
        voice = PiperVoice.load(str(voice_path), use_cuda=self.device == "cuda")
        self._loaded[language] = voice
        return voice

    def warm_up(self) -> None:
        samples = {
            Language.GERMAN: "Hallo.",
            Language.MANDARIN: "你好。",
        }
        for language, text in samples.items():
            output = self.synthesize(text, language)
            output.unlink(missing_ok=True)

    def synthesize(self, text: str, language: Language) -> Path:
        voice = self._load(language)
        with tempfile.NamedTemporaryFile(
            prefix="offline-interpreter-", suffix=".wav", delete=False
        ) as handle:
            output = Path(handle.name)
        try:
            with wave.open(str(output), "wb") as wav_file:
                if hasattr(voice, "synthesize_wav"):
                    from piper import SynthesisConfig

                    voice.synthesize_wav(
                        text,
                        wav_file,
                        syn_config=SynthesisConfig(length_scale=self.length_scale),
                    )
                else:  # Compatibility with piper-tts 1.2.
                    voice.synthesize(text, wav_file, length_scale=self.length_scale)
            return output
        except Exception:
            output.unlink(missing_ok=True)
            raise
