from __future__ import annotations

import tempfile
import wave
from collections.abc import Iterable, Mapping
from pathlib import Path

from lianiq.hardware import resolve_onnx_device
from lianiq.languages.errors import CapabilityMissingError
from lianiq.languages.registry import BUILTIN_REGISTRY, LanguageId, LanguageRegistry
from lianiq.languages.requirements import Requirement, RequirementKind


class PiperEngine:
    """Piper voices by language ID, each loaded on first use or by ``warm_up`` and cached.

    A language without a configured voice raises ``CapabilityMissingError``.
    """

    def __init__(
        self,
        voices: Mapping[str, Path],
        length_scale: float = 1.0,
        device: str = "auto",
        registry: LanguageRegistry = BUILTIN_REGISTRY,
    ) -> None:
        self.registry = registry
        self.voices: dict[LanguageId, Path] = {
            registry.get(language).id: path for language, path in voices.items()
        }
        self.length_scale = length_scale
        self.device = resolve_onnx_device(device)
        self._loaded: dict[LanguageId, object] = {}

    def _voice_path(self, language: str) -> tuple[LanguageId, Path]:
        language_id = self.registry.get(language).id
        voice_path = self.voices.get(language_id)
        if voice_path is None:
            raise CapabilityMissingError(Requirement(RequirementKind.VOICE, language_id))
        return language_id, voice_path

    def validate_voice_files(self, languages: Iterable[str] | None = None) -> None:
        """Check voice and metadata files of ``languages`` (default: every configured voice)."""
        missing: list[Path] = []
        for language in self.voices if languages is None else languages:
            _language_id, voice_path = self._voice_path(language)
            for required in (voice_path, Path(f"{voice_path}.json")):
                if not required.is_file():
                    missing.append(required)
        if missing:
            paths = ", ".join(str(path) for path in missing)
            raise FileNotFoundError(
                "Piper voice artifacts are missing: "
                f"{paths}. Provision license-reviewed voice and metadata files first."
            )

    def _load(self, language: str):
        language_id, voice_path = self._voice_path(language)
        if language_id in self._loaded:
            return self._loaded[language_id]
        self.validate_voice_files((language_id,))
        try:
            from piper import PiperVoice
        except ImportError as exc:
            raise RuntimeError("piper-tts is not installed") from exc
        voice = PiperVoice.load(str(voice_path), use_cuda=self.device == "cuda")
        self._loaded[language_id] = voice
        return voice

    def warm_up(self, languages: Iterable[str]) -> None:
        """Run one real synthesis per required voice; the sample is the native name."""
        for language in languages:
            output = self.synthesize(self.registry.get(language).native_name, language)
            output.unlink(missing_ok=True)

    def synthesize(self, text: str, language: str) -> Path:
        voice = self._load(language)
        with tempfile.NamedTemporaryFile(prefix="lianiq-", suffix=".wav", delete=False) as handle:
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
