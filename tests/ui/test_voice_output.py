"""Per-language voice switches and readiness through the real ``MainWindow`` (CAP-0167 WI-03).

A synthetic pair ``qaa``/``qab`` (BCP 47 private use) with spy adapters, offscreen: one switch
per pair language in Conversation and Settings, the state texts, the Start check of the
spoken plan, the plan bound at Start, **Open Language packs** and no ``voice-missing``
notice (contract.md §4, §7, §8; spec AC-01..AC-05, AC-28..AC-30). WI-04 playback is in
``test_voice_output_playback.py``.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest

from lianiq.config import TranslationEdgeConfig
from lianiq.languages import BUILTIN_LANGUAGES, LanguageRegistry
from lianiq.ui import notice_catalog as catalog
from lianiq.ui import strings
from lianiq.ui.shell.workspaces import WorkspaceId
from tests._spy_window import build_window, model_dir, spies  # noqa: F401
from tests.languages.synthetic import QAA, QAB, SYNTHETIC_LANGUAGES
from tests.ui._language_helpers import start, submit, transcript, wait_until

REGISTRY = LanguageRegistry((*BUILTIN_LANGUAGES, *SYNTHETIC_LANGUAGES))
NAME = {QAA: "Synthetic A", QAB: "Synthetic B"}


def synthetic_pair(voices: tuple[str, ...]):
    """Only the ``qaa``/``qab`` pair is ready; the voices in ``voices`` are on disk."""

    def configure(config, root: Path) -> None:
        config.languages.pair = [QAA, QAB]
        config.languages.routing, config.languages.fixed_source = "bidirectional", None
        config.speech_to_text.languages = [QAA, QAB]
        config.translation.edges = {
            f"{QAA}>{QAB}": TranslationEdgeConfig(str(model_dir(root, "mt-a-b"))),
            f"{QAB}>{QAA}": TranslationEdgeConfig(str(model_dir(root, "mt-b-a"))),
        }
        folder = root / "models" / "piper"
        config.tts.voices = {language: str(folder / f"{language}.onnx") for language in NAME}
        for language in voices:
            Path(config.tts.voices[language]).write_bytes(b"voice")

    return configure


@pytest.fixture
def open_window(tmp_path, monkeypatch, request, spies):  # noqa: F811
    def make(*voices: str, configure=None):
        def setup(config, root):
            synthetic_pair(voices)(config, root)
            if configure is not None:
                configure(config, root)

        window = build_window(tmp_path, monkeypatch, configure=setup, registry=REGISTRY)
        request.addfinalizer(window.close)
        return window

    return make


def rows(window):
    return window.conversation.voice_rows


def test_one_switch_per_language_with_name_voice_and_state_mirrored_in_settings(
    open_window,
) -> None:
    window = open_window(QAA, QAB)
    conversation, mirror = rows(window), window.settings.voice_rows
    assert conversation.languages() == mirror.languages() == (QAA, QAB)
    for language in (QAA, QAB):
        switch = conversation.switch(language)
        assert switch.text() == NAME[language] and switch.isChecked() and switch.isEnabled()
        assert switch.accessibleName() == f"Speak {NAME[language]}"
        label = conversation.state_label(language)
        assert label.text() == f"{language} · Ready"  # the path stem of the voice
        assert label.accessibleName() == f"{NAME[language]} voice: {language} · Ready"
        assert conversation.packs_button(language).isHidden()
        assert conversation.options_button(language).isHidden()  # no controls offered yet
    assert not conversation.replay_button.isHidden()
    assert not conversation.replay_button.isEnabled()
    assert conversation.replay_button.toolTip() == strings.VOICE_REPLAY_EMPTY
    assert window.config.languages.output == "spoken"

    mirror.switch(QAA).click()  # Settings changes Conversation and the saved choice

    assert not conversation.switch(QAA).isChecked() and not mirror.switch(QAA).isChecked()
    assert window.config.tts.output[QAA].enabled is False
    assert window.config.languages.output == "spoken"  # qab is still planned
    conversation.switch(QAB).click()
    assert not mirror.switch(QAB).isChecked()
    assert window.config.languages.output == "text"  # empty plan


def test_missing_voice_is_off_disabled_shows_the_state_and_opens_language_packs(
    open_window,
) -> None:
    window = open_window(QAB)
    row = rows(window)
    switch, label, packs = row.switch(QAA), row.state_label(QAA), row.packs_button(QAA)
    assert not switch.isChecked() and not switch.isEnabled()
    assert label.text() == strings.VOICE_STATE_MISSING
    assert not packs.isHidden() and packs.text() == strings.PACKS_OPEN
    assert packs.accessibleName() == f"Open Language packs for {NAME[QAA]}"
    assert window.notices.get(catalog.VOICE_MISSING) is None  # the row shows it (C §8)
    assert "Voice Synthetic A: Voice missing" in window.settings.readiness_rows()
    assert "Voice Synthetic B: Ready" in window.settings.readiness_rows()

    packs.click()

    assert window.navigation.current() is WorkspaceId.LANGUAGE_PACKS


def test_fixed_direction_disables_the_source_switch(open_window) -> None:
    window = open_window(QAA, QAB)
    window.mode_combo.setCurrentIndex(window.mode_combo.findData(QAA))
    row = rows(window)
    expected = f"Not an output language in {NAME[QAA]} → {NAME[QAB]}"
    assert row.state_label(QAA).text() == expected
    assert not row.switch(QAA).isEnabled() and row.switch(QAB).isChecked()


def test_asymmetric_voices_speak_only_the_ready_language_after_the_text(
    open_window,
    spies,  # noqa: F811
) -> None:
    window = open_window(QAB)
    start(window)
    assert window.pipeline.spoken_languages == {QAB}  # the plan bound at Start
    assert spies.synthesizer.warmed_languages == [QAB]
    assert not rows(window).switch(QAB).isEnabled()  # locked while running
    assert rows(window).switch(QAB).toolTip() == strings.LOCKED_TOOLTIP
    assert not window.settings.voice_rows.switch(QAB).isEnabled()

    submit(window, spies, transcript("alpha", QAA))  # into qab: shown and spoken
    assert wait_until(lambda: spies.synthesizer.calls)
    submit(window, spies, transcript("beta", QAB))  # into qaa: shown only
    assert wait_until(lambda: len(window.history) == 2)

    assert [language for _text, language in spies.synthesizer.calls] == [QAB]
    assert window.notices.get(catalog.VOICE_MISSING) is None


def test_start_with_a_switched_on_voice_needs_the_speakers(open_window) -> None:
    window = open_window(QAA, QAB)
    conversation = window.conversation
    unplugged = type(conversation.device_readiness())(microphone=True, playback=False)
    conversation.device_readiness = lambda: unplugged

    conversation.refresh_availability()
    assert not window.start_button.isEnabled()  # spoken plan: the playback device is missing

    for language in (QAA, QAB):
        rows(window).switch(language).click()  # both off: text-only needs no speakers

    assert window.start_button.isEnabled()
    assert window.config.languages.output == "text"


def test_no_voice_at_all_starts_text_only_without_a_voice_adapter(
    open_window,
    spies,  # noqa: F811
) -> None:
    window = open_window()
    row = rows(window)
    assert row.replay_button.isHidden() and row.stop_playback_button.isHidden()
    assert window.start_button.isEnabled()

    start(window)

    assert window.pipeline.spoken_languages == frozenset()
    assert spies.synthesizer is None  # no voice adapter constructed
    assert window.config.languages.output == "text"


def test_a_stored_off_choice_survives_a_new_window(open_window) -> None:
    def stored_off(config, _root) -> None:
        from lianiq.config_voice import VoiceOutputPreference

        config.tts.output = {QAA: VoiceOutputPreference(enabled=False)}

    window = open_window(QAA, QAB, configure=stored_off)
    assert not rows(window).switch(QAA).isChecked() and rows(window).switch(QAB).isChecked()
