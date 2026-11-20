from __future__ import annotations

import dataclasses
import io
import json
import tempfile
import wave
from collections.abc import Iterable, Mapping
from pathlib import Path

import numpy as np

from lianiq.hardware import resolve_onnx_device
from lianiq.languages.errors import CapabilityMissingError
from lianiq.languages.registry import BUILTIN_REGISTRY, LanguageId, LanguageRegistry
from lianiq.languages.requirements import Requirement, RequirementKind
from lianiq.tts.voice_controls import VoiceControls, VoiceOptions, check_speaker


def _synthesis_fields() -> frozenset[str]:
    """Field names of ``piper.SynthesisConfig``; none on the piper-tts 1.2 path."""
    try:
        from piper import SynthesisConfig
    except ImportError:
        return frozenset()
    return frozenset(field.name for field in dataclasses.fields(SynthesisConfig))


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
        self._speakers: dict[LanguageId, int] = {}

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

    def _speaker_count(self, language: str) -> int:
        """``num_speakers`` of the voice's ``.onnx.json`` (absent: 1); no model is loaded."""
        language_id, voice_path = self._voice_path(language)
        if language_id not in self._speakers:
            metadata = json.loads(Path(f"{voice_path}.json").read_text(encoding="utf-8"))
            self._speakers[language_id] = max(1, int(metadata.get("num_speakers") or 1))
        return self._speakers[language_id]

    def controls(self, language: str) -> VoiceControls:
        """Rate always; Volume iff ``SynthesisConfig`` has a ``volume`` field (contract §2)."""
        speakers = self._speaker_count(language)
        return VoiceControls(speakers, rate=True, volume="volume" in _synthesis_fields())

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
        """Run one real in-memory synthesis per required voice; the sample is the native name.

        No file is written, not even a temporary WAV (CAP-0177 AC-17: a meeting start warms up).
        """
        for language in languages:
            self.synthesize_pcm(self.registry.get(language).native_name, language)

    def synthesize(self, text: str, language: str, options: VoiceOptions | None = None) -> Path:
        voice, options = self._prepare(language, options)
        with tempfile.NamedTemporaryFile(prefix="lianiq-", suffix=".wav", delete=False) as handle:
            output = Path(handle.name)
        try:
            with wave.open(str(output), "wb") as wav_file:
                self._synthesize_into(voice, text, wav_file, options)
            return output
        except Exception:
            output.unlink(missing_ok=True)
            raise

    def synthesize_pcm(
        self, text: str, language: str, options: VoiceOptions | None = None
    ) -> tuple[np.ndarray, int]:
        """Synthesize ``text`` in memory: PCM16 mono samples and rate; no file is written."""
        voice, options = self._prepare(language, options)
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav_file:
            self._synthesize_into(voice, text, wav_file, options)
        buffer.seek(0)
        with wave.open(buffer, "rb") as wav_file:
            if wav_file.getnchannels() != 1 or wav_file.getsampwidth() != 2:
                raise RuntimeError("Piper must produce PCM16 mono audio")
            sample_rate = wav_file.getframerate()
            frames = wav_file.readframes(wav_file.getnframes())
        return np.frombuffer(frames, dtype="<i2").copy(), sample_rate

    def _prepare(self, language: str, options: VoiceOptions | None) -> tuple[object, VoiceOptions]:
        options = options or VoiceOptions()
        if options.speaker is not None:
            check_speaker(options, self._speaker_count(language), self._voice_path(language)[1])
        return self._load(language), options

    def _synthesize_into(
        self, voice, text: str, wav_file: wave.Wave_write, options: VoiceOptions
    ) -> None:
        length_scale = self.length_scale / options.rate
        if hasattr(voice, "synthesize_wav"):
            from piper import SynthesisConfig

            # Only the fields this piper-tts version has are passed (contract §2).
            values = {
                "length_scale": length_scale,
                "volume": options.volume,
                "speaker_id": options.speaker,
            }
            fields = _synthesis_fields()
            config = SynthesisConfig(**{k: v for k, v in values.items() if k in fields})
            voice.synthesize_wav(text, wav_file, syn_config=config)
        else:  # Compatibility with piper-tts 1.2: no volume.
            extra = {} if options.speaker is None else {"speaker_id": options.speaker}
            voice.synthesize(text, wav_file, length_scale=length_scale, **extra)
