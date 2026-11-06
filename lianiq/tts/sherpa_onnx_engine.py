from __future__ import annotations

import tempfile
import threading
import wave
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from lianiq.languages.errors import CapabilityMissingError
from lianiq.languages.registry import BUILTIN_REGISTRY, LanguageId, LanguageRegistry
from lianiq.languages.requirements import Requirement, RequirementKind

# Files of a sherpa-onnx VITS voice directory (the k2-fsa ``vits-icefall-*`` layout).
MODEL_FILE = "model.onnx"
LEXICON_FILE = "lexicon.txt"
TOKENS_FILE = "tokens.txt"
# Text-normalisation rules, applied in this order (``rule_fsts``), then ``rule.far``.
RULE_FST_FILES = ("phone.fst", "date.fst", "number.fst", "new_heteronym.fst")
RULE_FAR_FILE = "rule.far"
REQUIRED_FILES = (MODEL_FILE, LEXICON_FILE, TOKENS_FILE, *RULE_FST_FILES, RULE_FAR_FILE)

# Deterministic synthesis: with the upstream default noise the output varies per call
# and recognition of the synthesized speech became unreliable (CAP-0169 WI-09 spike).
NOISE_SCALE = 0.0
NOISE_SCALE_W = 0.0
PEAK_LEVEL = 0.9


@dataclass(frozen=True, slots=True)
class SherpaVoiceSettings:
    """Per-voice synthesis settings: speaker of a multi-speaker model and speaking rate."""

    speaker_id: int = 0
    length_scale: float = 1.0

    def __post_init__(self) -> None:
        if self.speaker_id < 0:
            raise ValueError("sherpa-onnx speaker_id must not be negative")
        if self.length_scale <= 0:
            raise ValueError("sherpa-onnx length_scale must be positive")


class SherpaOnnxEngine:
    """sherpa-onnx VITS voices by language ID, loaded on first use or by ``warm_up``.

    Each voice is a directory with the files in ``REQUIRED_FILES``. Synthesis runs on the
    CPU only; a requested CUDA device is ignored. A language without a configured voice
    raises ``CapabilityMissingError``.
    """

    def __init__(
        self,
        voices: Mapping[str, Path],
        settings: Mapping[str, SherpaVoiceSettings] | None = None,
        num_threads: int = 4,
        device: str = "auto",  # accepted for adapter parity; synthesis is CPU only
        registry: LanguageRegistry = BUILTIN_REGISTRY,
    ) -> None:
        if num_threads <= 0:
            raise ValueError("sherpa-onnx num_threads must be positive")
        self.registry = registry
        self.voices: dict[LanguageId, Path] = {
            registry.get(language).id: Path(path) for language, path in voices.items()
        }
        self.settings: dict[LanguageId, SherpaVoiceSettings] = {
            registry.get(language).id: value for language, value in (settings or {}).items()
        }
        self.num_threads = num_threads
        self.device = "cpu"
        self._loaded: dict[LanguageId, object] = {}
        self._lock = threading.Lock()  # serialises generate() across threads
        self._load_lock = threading.Lock()  # one model build per voice

    def _voice_path(self, language: str) -> tuple[LanguageId, Path]:
        language_id = self.registry.get(language).id
        voice_path = self.voices.get(language_id)
        if voice_path is None:
            raise CapabilityMissingError(Requirement(RequirementKind.VOICE, language_id))
        return language_id, voice_path

    def _settings(self, language_id: LanguageId) -> SherpaVoiceSettings:
        return self.settings.get(language_id, SherpaVoiceSettings())

    def validate_voice_files(self, languages: Iterable[str] | None = None) -> None:
        """Check the voice directory files of ``languages`` (default: every configured voice)."""
        missing: list[Path] = []
        for language in self.voices if languages is None else languages:
            _language_id, voice_path = self._voice_path(language)
            missing.extend(
                voice_path / name for name in REQUIRED_FILES if not (voice_path / name).is_file()
            )
        if missing:
            paths = ", ".join(str(path) for path in missing)
            raise FileNotFoundError(
                "sherpa-onnx voice artifacts are missing: "
                f"{paths}. Provision the pinned voice with scripts/download_models.py first."
            )

    def _load(self, language: str):
        language_id, voice_path = self._voice_path(language)
        with self._load_lock:
            loaded = self._loaded.get(language_id)
            if loaded is None:
                loaded = self._loaded[language_id] = self._build(language_id, voice_path)
            return loaded

    def _build(self, language_id: LanguageId, voice_path: Path):
        self.validate_voice_files((language_id,))
        try:
            import sherpa_onnx
        except ImportError as exc:
            raise RuntimeError("sherpa-onnx is not installed") from exc
        settings = self._settings(language_id)
        config = sherpa_onnx.OfflineTtsConfig(
            model=sherpa_onnx.OfflineTtsModelConfig(
                vits=sherpa_onnx.OfflineTtsVitsModelConfig(
                    model=str(voice_path / MODEL_FILE),
                    lexicon=str(voice_path / LEXICON_FILE),
                    tokens=str(voice_path / TOKENS_FILE),
                    noise_scale=NOISE_SCALE,
                    noise_scale_w=NOISE_SCALE_W,
                    length_scale=settings.length_scale,
                ),
                provider="cpu",
                num_threads=self.num_threads,
            ),
            rule_fsts=",".join(str((voice_path / name).resolve()) for name in RULE_FST_FILES),
            rule_fars=str((voice_path / RULE_FAR_FILE).resolve()),
            max_num_sentences=1,
        )
        tts = sherpa_onnx.OfflineTts(config)
        num_speakers = int(getattr(tts, "num_speakers", 0) or 0)
        if num_speakers and settings.speaker_id >= num_speakers:
            raise ValueError(
                f"sherpa-onnx speaker_id {settings.speaker_id} is out of range for the "
                f"voice in {voice_path} ({num_speakers} speakers)"
            )
        return tts

    def warm_up(self, languages: Iterable[str]) -> None:
        """Run one real synthesis per required voice; the sample is the native name."""
        for language in languages:
            output = self.synthesize(self.registry.get(language).native_name, language)
            output.unlink(missing_ok=True)

    def synthesize(self, text: str, language: str) -> Path:
        """Synthesize ``text`` to a PCM16 mono WAV temp file, peak-normalised to 0.9."""
        tts = self._load(language)
        language_id = self.registry.get(language).id
        with self._lock:
            audio = tts.generate(text, sid=self._settings(language_id).speaker_id, speed=1.0)
        samples = np.asarray(audio.samples, dtype=np.float32)
        if samples.size == 0:
            raise RuntimeError("sherpa-onnx produced no audio for the given text")
        peak = float(np.max(np.abs(samples)))
        if peak > 0.0:
            samples = samples * (PEAK_LEVEL / peak)
        pcm = (np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2")
        with tempfile.NamedTemporaryFile(prefix="lianiq-", suffix=".wav", delete=False) as handle:
            output = Path(handle.name)
        try:
            with wave.open(str(output), "wb") as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(int(audio.sample_rate))
                wav_file.writeframes(pcm.tobytes())
            return output
        except Exception:
            output.unlink(missing_ok=True)
            raise
