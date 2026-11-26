"""Run-time speech of the English ↔ Mandarin row E-40 (english-mandarin-pair e2e plan D-03).

No recording is committed: E1 ("We can deliver 250 units next Tuesday.") and Z1 ("我们下周
不能来。") are synthesised in the VM, before the app starts, with the image's voices through
Lianiq's own TTS engine (``build_pipeline(AppConfig.load()).voice_synthesizer()``: Piper
``en_US-ljspeech-high`` for English, the configured Mandarin voice for Z1), as the
qualification kit speaks its sentences. Each file is rendered like the committed fixtures
(``make_fixtures.render``: 0.5 s lead, 1 s tail, 16 kHz mono 16-bit PCM) into
``%TEMP%\\lianiq-e2e\\speech``. The texts go to ``ctx.secrets`` before synthesis; neither a
text nor PCM is stored in evidence, and ``discard`` deletes the files after the row.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from native_e2e.context import RunContext

EN, ZH = "conv_en_16k.wav", "conv_zh_z1_16k.wav"
# name → (language, sentence) segments, as ``make_fixtures.FIXTURES``
SPEECH: dict[str, tuple[tuple[str, str], ...]] = {
    EN: (("en", "We can deliver 250 units next Tuesday."),),
    ZH: (("zh-Hans", "我们下周不能来。"),),
}


def synthesizer() -> Any:
    """Lianiq's configured voice synthesizer (no model is loaded before the first call)."""
    from lianiq.app import build_pipeline
    from lianiq.config import AppConfig

    return build_pipeline(AppConfig.load()).voice_synthesizer()


def _voice(engine: Any, language: str):
    def synth(text: str) -> tuple[Any, int]:
        import numpy

        pcm, rate = engine.synthesize_pcm(text, language)
        return numpy.asarray(pcm, dtype="float32") / 32768.0, int(rate)

    return synth


def speech_wav(ctx: RunContext, name: str, engine: Any = None) -> Path:
    """Synthesise the WAV ``name`` of ``SPEECH`` into the job's temp folder; its path."""
    from native_e2e.data.make_fixtures import render, write_wav

    segments = SPEECH[name]
    for _language, text in segments:
        if text not in ctx.secrets:
            ctx.secrets.append(text)
    engine = engine if engine is not None else synthesizer()
    voices = {language: _voice(engine, language) for language, _text in segments}
    path = ctx.temp / "speech" / name
    write_wav(path, render(segments, voices))
    return path


def speech_wavs(ctx: RunContext, names: Iterable[str] = (EN, ZH)) -> list[Path]:
    """Every WAV of ``names`` with one synthesizer."""
    engine = synthesizer()
    return [speech_wav(ctx, name, engine) for name in names]


def discard(paths: Iterable[Path]) -> None:
    for path in paths:
        Path(path).unlink(missing_ok=True)
