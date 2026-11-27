"""Only Piper, sherpa-onnx and the installed Windows voice synthesize speech (CAP-0167 AC-21, static half).

Every import in ``lianiq/`` (module level or inside a function) is read with ``ast``. A
third-party package outside ``THIRD_PARTY`` fails, so a new engine or cloud SDK cannot slip
in; ``piper`` and ``sherpa_onnx`` are imported only by their engine modules, and the
settings accept no other engine name. The socket-guarded run is in
``tests/ui/test_voice_offline.py``.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from lianiq.config_voice import VOICE_ENGINES

ROOT = Path(__file__).resolve().parents[1]
TTS_MODULES = {
    "piper": "lianiq/tts/piper_engine.py",
    "sherpa_onnx": "lianiq/tts/sherpa_onnx_engine.py",
    "winrt": "lianiq/tts/system_voice.py",  # installed Windows voice (lianiq#81)
}
# Every third-party package lianiq imports, by role. Speech synthesis: only TTS_MODULES.
THIRD_PARTY = {
    *TTS_MODULES,
    "faster_whisper",  # recognition
    "ctranslate2",
    "transformers",  # MarianMT
    "torch",
    "onnxruntime",
    "numpy",
    "sounddevice",
    "PySide6",
}


def imports() -> dict[str, set[str]]:
    """Top-level module name → the files (relative, ``/``) that import it."""
    found: dict[str, set[str]] = {}
    for path in sorted((ROOT / "lianiq").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            else:
                continue
            for name in names:
                found.setdefault(name.split(".")[0], set()).add(path.relative_to(ROOT).as_posix())
    return found


def test_ac21_lianiq_imports_no_third_party_package_beyond_the_known_ones() -> None:
    found = imports()
    third_party = {
        name for name in found if name not in sys.stdlib_module_names and name != "lianiq"
    }
    assert third_party - THIRD_PARTY == set()
    assert set(TTS_MODULES) <= third_party  # the walk sees both engines


def test_ac21_only_the_engine_modules_import_piper_and_sherpa_onnx() -> None:
    found = imports()
    for module, owner in TTS_MODULES.items():
        assert found[module] == {owner}


def test_ac21_the_settings_accept_only_piper_and_sherpa_onnx() -> None:
    assert VOICE_ENGINES == {"piper", "sherpa-onnx"}
