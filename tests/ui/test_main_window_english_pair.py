"""English ↔ Mandarin (Simplified) in the pair control and Conversation (CAP-0181 AC-06, AC-07, AC-11).

pytest-qt style over spy adapters, like ``test_main_window_languages.py``; code evidence only.
"""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from lianiq.config import TranslationEdgeConfig
from lianiq.languages import BUILTIN_REGISTRY
from tests._spy_window import model_dir, spies  # noqa: F401
from tests.ui._language_helpers import (
    EN,
    PAIR_NAME,
    PLANNED,
    ZH,
    items,
    open_window,
    start,
    submit,
    transcript,
    wait_until,
)

EN_PAIR = "English ↔ Mandarin (Simplified)"


def with_english(*, reverse: bool = True, voice: bool = True):
    def configure(config, root: Path) -> None:
        edges = config.translation.edges
        edges["en>zh-Hans"] = TranslationEdgeConfig(str(model_dir(root, "opus-mt-en-zh")))
        if reverse:
            edges["zh-Hans>en"] = TranslationEdgeConfig(str(model_dir(root, "opus-mt-zh-en")))
        config.tts.voices["en"] = str(root / "models" / "piper" / "en.onnx")
        if voice:
            Path(config.tts.voices["en"]).write_bytes(b"voice")

    return configure


def test_ac06_pair_control_lists_english_mandarin_and_no_german_english(
    tmp_path,
    monkeypatch,
    request,
    spies,  # noqa: F811
) -> None:
    window = open_window(tmp_path, monkeypatch, request, configure=with_english())

    assert items(window.pair_combo) == [PAIR_NAME, EN_PAIR, *PLANNED]
    assert not [text for text in items(window.pair_combo) if "German ↔ English" in text]


def test_ac06_missing_reverse_pack_blocks_the_pair_and_names_the_translation(
    tmp_path,
    monkeypatch,
    request,
    spies,  # noqa: F811
) -> None:
    # As CAP-0169 AC-03: the one installed direction stays selectable as a fixed direction.
    window = open_window(tmp_path, monkeypatch, request, configure=with_english(reverse=False))
    window.pair_combo.setCurrentText(EN_PAIR)
    missing = "Not available: missing translation Mandarin (Simplified) → English"

    assert window.mode_combo.currentIndex() == 0  # Automatic
    assert not window.mode_combo.model().item(0).isEnabled()
    assert window.mode_combo.model().item(0).toolTip() == missing
    assert not window.start_button.isEnabled()
    assert window.statusBar().currentMessage() == missing


def test_ac07_english_pair_without_english_voice_runs_with_text_output(
    tmp_path,
    monkeypatch,
    request,
    spies,  # noqa: F811
) -> None:
    window = open_window(tmp_path, monkeypatch, request, configure=with_english(voice=False))
    window.pair_combo.setCurrentText(EN_PAIR)

    assert window.current_pair() == BUILTIN_REGISTRY.pair(EN, ZH)
    assert window.voice_rows.state_label(EN).text() == "Voice missing"
    assert not window.voice_rows.switch(EN).isEnabled()
    assert window.start_button.isEnabled()
    start(window)
    submit(window, spies, transcript("Good morning", "en"))
    assert wait_until(lambda: len(window.history) == 1)
    assert spies.synthesizer.calls == []  # into Mandarin: the Mandarin voice is not required
    window.stop_listening()


def test_ac11_route_test_speaks_the_english_phrase() -> None:
    """The Call Bridge route test with local language English uses the English phrase."""
    from lianiq.ui.workspaces.call_bridge import CallBridgeWorkspace

    phrase = CallBridgeWorkspace.route_test_phrase(None, BUILTIN_REGISTRY.get("en").id)
    assert phrase == "Headphone test."
