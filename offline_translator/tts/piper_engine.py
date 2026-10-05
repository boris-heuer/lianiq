from __future__ import annotations

import tempfile
import wave
from pathlib import Path

from offline_translator.domain import Language


class PiperEngine:
    """Keeps both Piper voices cached to avoid process and model-load latency."""

    def __init__(
        self,
        de_voice_path: Path,
        zh_voice_path: Path,
        length_scale: float = 1.0,
        use_cuda: bool = False,
    ) -> None:
        self.voices = {
            Language.GERMAN: de_voice_path,
            Language.MANDARIN: zh_voice_path,
        }
        self.length_scale = length_scale
        self.use_cuda = use_cuda
        self._loaded: dict[Language, object] = {}

    def _load(self, language: Language):
        if language in self._loaded:
            return self._loaded[language]
        voice_path = self.voices[language]
        if not voice_path.exists() or not Path(f"{voice_path}.json").exists():
            raise FileNotFoundError(
                f"Piper voice is missing: {voice_path}. Run scripts/download_models.py first."
            )
        try:
            from piper import PiperVoice
        except ImportError as exc:
            raise RuntimeError("piper-tts is not installed") from exc
        voice = PiperVoice.load(str(voice_path), use_cuda=self.use_cuda)
        self._loaded[language] = voice
        return voice

    def warm_up(self) -> None:
        self._load(Language.GERMAN)
        self._load(Language.MANDARIN)

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
