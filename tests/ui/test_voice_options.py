"""**Voice options…**: the dialog, its controls per engine and the Conversation lock (WI-05).

Contract.md §7, spec AC-14, AC-16 and AC-26: the dialog shows exactly the controls the
engine reports, **Voice options…** is hidden when it reports none, each change is saved at
once and a running Conversation speaks its next turn with it, and no voice model is loaded
before Start, Replay or a sherpa-onnx speaker count read by the dialog. The ``qaa``/``qab``
window of ``test_voice_output.py`` over spy adapters, offscreen.
"""

from __future__ import annotations

import itertools
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from lianiq.config_voice import VoicePreferences
from lianiq.tts.voice_controls import VoiceControls, VoiceOptions
from lianiq.tts.voice_router import NO_CONTROLS
from lianiq.ui import strings
from lianiq.ui.shell.workspaces import WorkspaceId
from tests._spy_window import spies  # noqa: F401
from tests.languages.synthetic import QAA, QAB
from tests.ui._language_helpers import click, start, submit, transcript, wait_until
from tests.ui.test_voice_output import REGISTRY, open_window, rows  # noqa: F401

COMBINATIONS = [
    VoiceControls(speakers, rate, volume)
    for speakers, rate, volume in itertools.product((1, 3), (False, True), (False, True))
]


def dialog_for(window, controls: VoiceControls, load=None, saved=None):
    from lianiq.ui.voice_options_dialog import VoiceOptionsDialog

    preferences = VoicePreferences(window.config, REGISTRY)
    save = (lambda: saved.append(True)) if saved is not None else None
    return VoiceOptionsDialog(QAB, controls, preferences, REGISTRY, load, window, save)


def with_controls(window, controls) -> None:
    """The pipeline reports ``controls[language]`` (fake engines), before and after Start."""
    window.pipeline.voice_controls = lambda language: controls[language]
    window.conversation.refresh_availability()


@pytest.mark.parametrize("controls", COMBINATIONS, ids=str)
def test_ac14_the_dialog_shows_exactly_the_controls_the_engine_offers(
    open_window,  # noqa: F811
    controls,
) -> None:
    window = open_window(QAA, QAB)
    dialog = dialog_for(window, controls)
    assert dialog.windowTitle() == "Voice options — Synthetic B"
    assert (dialog.voice_combo is not None) is (controls.speakers > 1)
    assert (dialog.rate_slider is not None) is controls.rate
    assert (dialog.volume_slider is not None) is controls.volume
    assert dialog.loading.isHidden()
    if dialog.voice_combo is not None:
        combo = dialog.voice_combo
        assert [combo.itemText(i) for i in range(combo.count())] == [
            "Speaker 1",
            "Speaker 2",
            "Speaker 3",
        ]
        assert combo.accessibleName() == "Voice"
    if dialog.rate_slider is not None:
        assert dialog.rate_slider.accessibleName() == "Rate"
        assert dialog.rate_slider.accessibleDescription() == "1.00×"
    if dialog.volume_slider is not None:
        assert dialog.volume_slider.accessibleName() == "Volume"
        assert dialog.volume_slider.accessibleDescription() == "100 %"


def test_ac14_voice_options_is_shown_only_for_a_voice_with_a_control(open_window) -> None:  # noqa: F811
    window = open_window(QAA, QAB)
    with_controls(window, {QAA: NO_CONTROLS, QAB: VoiceControls(1, rate=True, volume=False)})
    for voice_rows in (rows(window), window.settings.voice_rows):
        assert voice_rows.options_button(QAA).isHidden()
        assert not voice_rows.options_button(QAB).isHidden()


def test_each_change_is_saved_at_once_and_keeps_what_the_engine_lacks(open_window) -> None:  # noqa: F811
    window = open_window(QAA, QAB)
    preferences = VoicePreferences(window.config, REGISTRY)
    preferences.set_options(QAB, VoiceOptions(speaker=None, rate=1.0, volume=0.5))
    saved: list[bool] = []
    dialog = dialog_for(window, VoiceControls(3, rate=True, volume=False), saved=saved)

    dialog.rate_slider.setValue(125)
    assert preferences.options(QAB) == VoiceOptions(None, 1.25, 0.5)  # volume kept
    assert dialog.rate_value.text() == "1.25×" and saved == [True]
    dialog.voice_combo.setCurrentIndex(2)
    assert preferences.options(QAB) == VoiceOptions(2, 1.25, 0.5) and len(saved) == 2


def test_ac26_a_sherpa_voice_loads_its_speaker_count_on_a_worker_thread(open_window) -> None:  # noqa: F811
    window = open_window(QAA, QAB)
    unknown = VoiceControls(None, rate=True, volume=False)
    dialog = dialog_for(window, unknown, load=lambda: VoiceControls(4, True, False))
    assert dialog.loading.text() == strings.VOICE_LOADING
    assert wait_until(lambda: dialog.voice_combo is not None)
    assert dialog.loading.isHidden() and dialog.voice_combo.count() == 4


def test_ac26_no_voice_is_constructed_or_loaded_by_launch_conversation_or_settings(
    open_window,  # noqa: F811
    spies,  # noqa: F811
) -> None:
    def metadata(config, _root) -> None:  # Piper metadata: read for the controls only
        for voice in config.tts.voices.values():
            Path(f"{voice}.json").write_text('{"num_speakers": 1}', encoding="utf-8")

    window = open_window(QAA, QAB, configure=metadata)
    window.show_workspace(WorkspaceId.CONVERSATION)
    window.show_workspace(WorkspaceId.SETTINGS)
    assert not rows(window).options_button(QAB).isHidden()  # Rate, from the metadata
    assert spies.constructed == []

    with_controls(window, {QAA: NO_CONTROLS, QAB: VoiceControls(None, True, False)})
    window.show_workspace(WorkspaceId.CONVERSATION)
    click(rows(window).options_button(QAB))
    dialog = window.conversation.voice_dialog
    assert dialog is not None and dialog.isVisible()
    dialog.load_thread.join(timeout=5.0)
    assert spies.constructed == ["synthesizer"]  # the speaker count needs the voice
    dialog.accept()


def test_ac16_a_running_conversation_locks_the_switches_and_speaks_the_new_rate(
    open_window,  # noqa: F811
    spies,  # noqa: F811
) -> None:
    window = open_window(QAA, QAB)
    window.pipeline.playback = lambda _path, _device: None
    with_controls(window, {QAA: NO_CONTROLS, QAB: VoiceControls(1, True, False)})
    start(window)
    for voice_rows in (rows(window), window.settings.voice_rows):
        assert not voice_rows.switch(QAB).isEnabled()
        assert voice_rows.switch(QAB).toolTip() == strings.LOCKED_TOOLTIP
        assert voice_rows.options_button(QAB).isEnabled()  # the dialog stays usable

    window.show_workspace(WorkspaceId.SETTINGS)
    click(window.settings.voice_rows.options_button(QAB))
    dialog = window.conversation.voice_dialog
    dialog.rate_slider.setValue(125)
    dialog.accept()
    submit(window, spies, transcript("eins", QAA))

    assert wait_until(lambda: len(spies.synthesizer.calls) == 1)
    assert spies.synthesizer.calls[0][1] == QAB
    assert spies.synthesizer.options[0].rate == 1.25
    window.stop_listening()
