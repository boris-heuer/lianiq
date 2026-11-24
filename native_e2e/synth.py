"""Speech fixtures synthesised in the VM when they are not committed (spec §2.1.4; AC-03).

The Mandarin fixtures (``conv_zh_16k.wav``, ``listen_zh_de_16k.wav``) cannot be committed:
the host's copy of the Mandarin voice is unreadable. ``speech_wav(ctx, name)`` therefore
returns ``fixtures.checked(name)`` when the fixture is pinned, present and unchanged, and
otherwise renders it once per run from ``make_fixtures.FIXTURES`` with the image's own voices
(``models_dir``: Piper ``de_DE-thorsten-medium`` and the sherpa-onnx Mandarin voice, built as
``lianiq.tts.sherpa_onnx_engine`` builds it), resampled with the app's resampler to 16 kHz
mono 16-bit, into ``ctx.temp/fixtures``. Only the image models are read, so a row may call it
while the ``models`` junction points at a scratch folder.

In both cases the fixture's texts are appended to ``ctx.secrets`` first, so no stored
artifact can carry them; the WAV stays in the VM and a row stores at most its SHA-256.
``None`` (unknown name, missing voice, any synthesis error, or not 16 kHz mono 16-bit) means
the row is ``blocked`` with ``fixture-missing``. Synthesis is never retried within a run.
"""

from __future__ import annotations

import wave
from pathlib import Path
from typing import TYPE_CHECKING

from native_e2e import fixtures, models_swap
from native_e2e.data import make_fixtures

if TYPE_CHECKING:
    from native_e2e.context import RunContext

STATE_KEY = "synth_fixtures"  # name → path of the WAV rendered in this run, or None
FIXTURE_MISSING = "fixture-missing"


def _valid(path: Path) -> bool:
    try:
        with wave.open(str(path), "rb") as handle:
            shape = (handle.getnchannels(), handle.getsampwidth(), handle.getframerate())
            return shape == (1, 2, make_fixtures.RATE) and handle.getnframes() > 0
    except (OSError, EOFError, wave.Error):
        return False


def _render(ctx: RunContext, name: str) -> Path | None:
    out = ctx.temp / "fixtures"
    try:
        make_fixtures.make(models_swap.image_models(ctx), [name], out)
    except Exception:  # noqa: BLE001 - no voice, no engine or a synthesis error: blocked
        return None
    path = out / name
    return path if _valid(path) else None


def speech_wav(ctx: RunContext, name: str) -> Path | None:
    """The WAV of fixture ``name``: the pinned file, else one rendered in the VM, else None."""
    if name not in make_fixtures.FIXTURES:
        return None
    fixtures.remember(ctx, name)
    found = fixtures.checked(name)
    if found is not None:
        return found
    rendered: dict[str, Path | None] = ctx.state.setdefault(STATE_KEY, {})
    if name not in rendered:
        rendered[name] = _render(ctx, name)
    return rendered[name]
