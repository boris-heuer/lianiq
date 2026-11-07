"""The Settings workspace (CAP-0168 WI-02; spec §2.3.3, §2.3.6).

pytest-qt style offscreen UI tests: AC-12 (model profile and compute device as full
read-only text in Settings › Diagnostics), the Voice output section mirrored with
Conversation, and the readiness summary.
"""

from __future__ import annotations

import os
import re

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from lianiq.ui.shell.workspaces import WorkspaceId
from tests.test_requirement_scoped_loading import build_window, spies  # noqa: F401
from tests.ui.test_main_window_languages import start, without_mandarin_voice
from tests.ui.test_main_window_wi08_fixes import (  # noqa: F401 - autouse Segoe UI fixture
    _load_windows_ui_font,
    use_windows_ui_font,
)
from tests.ui.test_shell_navigation import resize


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


def test_voice_output_is_mirrored_with_conversation(window) -> None:
    mirror = window.settings.voice_output_checkbox
    source = window.tts_checkbox
    assert mirror.text() == "Voice output" and mirror.accessibleName() == "Voice output"
    assert mirror.isChecked() == source.isChecked() and mirror.isEnabled()

    before = mirror.isChecked()
    mirror.click()  # the checkbox spans the row; QAbstractButton.click() toggles it reliably
    assert mirror.isChecked() is not before
    assert source.isChecked() is mirror.isChecked()
    assert window.config.voice_output is mirror.isChecked()
    source.click()
    assert source.isChecked() is before
    assert mirror.isChecked() is source.isChecked()
    assert window.config.voice_output is source.isChecked()

    window.show_workspace(WorkspaceId.CONVERSATION)
    start(window)  # the output is bound at Start: both are locked
    assert not source.isEnabled() and not mirror.isEnabled()
    assert mirror.toolTip() == source.toolTip() != ""
    window.stop_listening()
    assert source.isEnabled() and mirror.isEnabled() and mirror.toolTip() == ""


def test_readiness_summary_names_the_pair_and_each_mode(window) -> None:
    window.show_workspace(WorkspaceId.SETTINGS)
    rows = window.settings.readiness_field.text().splitlines()
    assert rows[:3] == [
        "Language pair: German ↔ Mandarin (Simplified)",
        "Conversation: Ready",
        "Voice output: Ready",
    ]
    assert rows[3].startswith("Call Bridge: Not available: missing ")
    assert "endpoint" in rows[3]  # no endpoints are assigned in this window


def test_readiness_summary_and_mirror_show_a_missing_voice(tmp_path, spies, monkeypatch) -> None:  # noqa: F811
    window = build_window(tmp_path, monkeypatch, configure=without_mandarin_voice)
    try:
        window.show_workspace(WorkspaceId.SETTINGS)
        rows = window.settings.readiness_field.text().splitlines()
        assert "Conversation: Ready" in rows
        assert "Voice output: Not available: missing voice Mandarin (Simplified)" in rows
        mirror = window.settings.voice_output_checkbox
        assert not mirror.isEnabled() and not mirror.isChecked()
        assert mirror.toolTip() == window.tts_checkbox.toolTip() != ""
    finally:
        window.close()
