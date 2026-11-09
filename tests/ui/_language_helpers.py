"""Shared helpers for the main window language-control tests (CAP-0169 WI-06).

Used by ``test_main_window_languages*.py`` and by the shell and accessibility tests that
drive a Conversation session: transcripts, Start, submitting a turn, settings variants and
the offscreen ``window`` fixture over spy adapters.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from lianiq.domain import AudioUtterance, Transcript
from lianiq.languages import LanguageId
from tests._spy_window import build_window
from tests.ui.test_main_window_session import click, wait_until

DE = LanguageId("de")
ZH = LanguageId("zh-Hans")
EN = LanguageId("en")
AUDIO = AudioUtterance(np.zeros(1_600, dtype=np.float32), 16_000)
PAIR_NAME = "German ↔ Mandarin (Simplified)"
AUTOMATIC = "Automatic (German ↔ Mandarin (Simplified))"
DE_TO_ZH = "German → Mandarin (Simplified)"
ZH_TO_DE = "Mandarin (Simplified) → German"
PLANNED = [
    "English – planned, unavailable",
    "Spanish – planned, unavailable",
    "French – planned, unavailable",
]
LOCKED = "Stop the session to change language pair or mode"


def transcript(text: str, language: str | None, probability: float = 0.95, code: str = ""):
    detected = None if language is None else LanguageId(language)
    return Transcript(text, detected, probability, 0.1, code or (language or ""))


def items(combo) -> list[str]:
    return [combo.itemText(index) for index in range(combo.count())]


def blocks(editor) -> list[str]:
    """The result blocks of a text panel, in display order."""
    return [block.strip() for block in editor.toPlainText().split("\n\n") if block.strip()]


def item_enabled(combo, index: int) -> bool:
    return combo.model().item(index).isEnabled()


def press(widget, key) -> None:
    from PySide6.QtTest import QTest

    QTest.keyClick(widget, key)


def start(window) -> None:
    click(window.start_button)
    assert wait_until(lambda: window.capture.running)


def submit(window, spies, *results) -> None:
    spies.recognizer.results.extend(results)
    window.runner.submit(AUDIO)


def only_de_to_zh_edge(config, _root) -> None:
    """Settings with only the edge ``de>zh-Hans`` (AC-03, VoR-02)."""
    del config.translation.edges["zh-Hans>de"]


def without_mandarin_voice(config, _root) -> None:
    """Both STT languages and both edges, but no ``zh-Hans`` voice (AC-08)."""
    Path(config.tts.voices["zh-Hans"]).unlink()
    config.voice_output = True  # the saved preference is spoken output


# The explicit name keeps the fixture "window" for test modules importing this function.
# It requests ``spies``, which the test module imports from ``tests/_spy_window.py``.
@pytest.fixture(name="window")
def language_window(tmp_path, spies, monkeypatch):
    window = build_window(tmp_path, monkeypatch)
    yield window
    window.close()


def open_window(tmp_path, monkeypatch, request, **options):
    window = build_window(tmp_path, monkeypatch, **options)
    request.addfinalizer(window.close)
    return window


def visible_texts(window) -> list[str]:
    from PySide6.QtWidgets import QAbstractButton, QComboBox, QLabel, QPlainTextEdit

    texts = [window.windowTitle(), window.statusBar().currentMessage()]
    for label in window.findChildren(QLabel):
        texts.append(label.text())
    for button in window.findChildren(QAbstractButton):
        texts += [button.text(), button.toolTip()]
    for combo in window.findChildren(QComboBox):
        texts += items(combo)
    for editor in window.findChildren(QPlainTextEdit):
        texts += [editor.toPlainText(), editor.placeholderText()]
    return texts


def assert_no_language_codes(window) -> None:
    for text in visible_texts(window):
        assert not re.search(r"\b(DE|ZH)\b", text), text
