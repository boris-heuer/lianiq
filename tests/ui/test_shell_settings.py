"""The Settings workspace (CAP-0168 WI-02; spec §2.3.3, §2.3.6).

pytest-qt style offscreen UI tests: AC-12 (model profile and compute device as full
read-only text in Settings › Diagnostics), the voice rows mirrored with
Conversation, and the readiness summary.
"""

from __future__ import annotations

import os
import re

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from lianiq.ui.shell.workspaces import WorkspaceId
from tests._spy_window import build_window, spies  # noqa: F401
from tests.ui._language_helpers import start, without_mandarin_voice
from tests.ui._navigation_helpers import resize
from tests.ui.test_main_window_wi08_fixes import (  # noqa: F401 - autouse Segoe UI fixture
    _load_windows_ui_font,
    use_windows_ui_font,
)


@pytest.fixture
def window(tmp_path, spies, monkeypatch):  # noqa: F811
    window = build_window(tmp_path, monkeypatch)
    use_windows_ui_font(window)
    window.show_workspace(WorkspaceId.SETTINGS)
    yield window
    window.stop_listening()
    window.close()


def shows_full_text(label) -> bool:
    from PySide6.QtCore import Qt

    text = label.text()
    return (
        bool(text)
        and not label.wordWrap()
        and label.fontMetrics().horizontalAdvance(text) <= label.contentsRect().width()
        and not label.textInteractionFlags() & Qt.TextInteractionFlag.TextEditable
    )


@pytest.mark.parametrize("size", [(1280, 720), (850, 560)])
def test_ac12_model_profile_and_compute_device_are_full_read_only_text(window, size) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QComboBox, QLabel

    resize(window, *size)
    assert window.current_workspace() is WorkspaceId.SETTINGS
    profile, device = window.model_profile_field, window.compute_device_field
    assert isinstance(profile, QLabel) and isinstance(device, QLabel)  # text, not a control
    assert profile.text() == "Balanced · Whisper small + MarianMT"
    assert re.fullmatch(r"Speech recognition: (CPU|CUDA) · Translation: (CPU|CUDA)", device.text())
    for field, name in ((profile, "Model profile"), (device, "Compute device")):
        assert field.isVisible()
        assert shows_full_text(field), (field.text(), field.contentsRect().width())
        assert field.accessibleName() == name
        assert field.focusPolicy() & Qt.FocusPolicy.TabFocus  # a named, readable Tab stop
    page = window.workspace_pages[WorkspaceId.SETTINGS]
    assert page.isAncestorOf(profile) and page.isAncestorOf(device)
    assert not any(c.accessibleName() == "Model profile" for c in window.findChildren(QComboBox))


def test_ac12_compute_device_reports_the_started_recogniser(window, spies) -> None:  # noqa: F811
    window.show_workspace(WorkspaceId.CONVERSATION)
    start(window)
    spies.recognizer.device = "cuda"
    window.show_workspace(WorkspaceId.SETTINGS)
    assert window.compute_device_field.text().startswith("Speech recognition: CUDA · ")


def test_voice_rows_are_mirrored_with_conversation(window) -> None:
    mirror, source = window.settings.voice_rows, window.voice_rows
    assert mirror.languages() == source.languages() != ()
    language = source.languages()[0]
    assert mirror.switch(language).text() == source.switch(language).text()
    assert mirror.switch(language).isChecked() and mirror.switch(language).isEnabled()

    mirror.switch(language).click()
    assert not source.switch(language).isChecked()
    assert window.config.tts.output[language].enabled is False
    source.switch(language).click()
    assert mirror.switch(language).isChecked()

    window.show_workspace(WorkspaceId.CONVERSATION)
    start(window)  # the plan is bound at Start: both are locked
    assert not source.switch(language).isEnabled() and not mirror.switch(language).isEnabled()
    assert mirror.switch(language).toolTip() == source.switch(language).toolTip() != ""
    window.stop_listening()
    assert mirror.switch(language).isEnabled() and mirror.switch(language).toolTip() == ""


def test_readiness_summary_names_the_pair_and_each_mode(window) -> None:
    window.show_workspace(WorkspaceId.SETTINGS)
    rows = window.settings.readiness_field.text().splitlines()
    assert rows[:4] == [
        "Language pair: German ↔ Mandarin (Simplified)",
        "Conversation: Ready",
        "Voice German: Ready",
        "Voice Mandarin (Simplified): Ready",
    ]
    assert rows[4].startswith("Call Bridge: Not available: missing ")
    assert "endpoint" in rows[4]  # no endpoints are assigned in this window


def test_readiness_summary_and_mirror_show_a_missing_voice(tmp_path, spies, monkeypatch) -> None:  # noqa: F811
    window = build_window(tmp_path, monkeypatch, configure=without_mandarin_voice)
    try:
        window.show_workspace(WorkspaceId.SETTINGS)
        rows = window.settings.readiness_field.text().splitlines()
        assert "Conversation: Ready" in rows
        assert "Voice Mandarin (Simplified): Voice missing" in rows
        mirror = window.settings.voice_rows
        language = mirror.languages()[1]
        assert not mirror.switch(language).isEnabled() and not mirror.switch(language).isChecked()
        assert mirror.state_label(language).text() == "Voice missing"
        assert not mirror.packs_button(language).isHidden()
    finally:
        window.close()
