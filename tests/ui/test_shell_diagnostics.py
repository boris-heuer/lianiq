"""Settings › Diagnostics: notice history, **Copy** and **Export…** (CAP-0168 WI-03; AC-27 UI).

After a Call Bridge session with endpoint IDs, a stale saved endpoint ID, the model and
project paths and a failed export folder in the log, Copy and Export… output contains no
transcript text, absolute path, username or endpoint ID. Cancel and a write error keep the
log and show a notice without "saved"; no network access occurs. Focus returns to
**Export…** after the dialog (AC-28 for this control).
"""

from __future__ import annotations

import getpass
import os
import re
import socket
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from lianiq.call_bridge.contracts import AudioEndpointRef, EndpointFlow, EndpointRole
from lianiq.ui.shell.workspaces import WorkspaceId
from tests.test_requirement_scoped_loading import spies  # noqa: F401
from tests.ui import test_main_window_call_bridge as bridge_tests
from tests.ui.test_main_window_languages import start, submit, transcript, wait_until
from tests.ui.test_main_window_session import click

SETTINGS = WorkspaceId.SETTINGS
GUID = "{{0.0.{flow}.00000000}}.{{6f1c2a3b-0d4e-4f5a-9b6c-7d8e9f0a1b{index:02d}}}"
STALE_ID = "windows-mmdevice:v1:render:{0.0.0.00000000}.{11111111-2222-3333-4444-555555555555}"
ABSOLUTE_PATH = re.compile(r"\b[A-Za-z]:[\\/]|\\\\\w|(?<![\w:<])/(home|Users|tmp|var|private)\b")
ENDPOINT_ID = re.compile(r"windows-mmdevice:|audio-endpoint:|\{\d+\.\d+\.\d+\.[0-9a-f]{8}\}")


def native_mapping() -> dict[EndpointRole, AudioEndpointRef]:
    """Call Bridge endpoints with real-format native identities."""
    result = {}
    for index, role in enumerate(EndpointRole):
        capture = role in {EndpointRole.LOCAL_MICROPHONE, EndpointRole.CALL_SPEAKER_CAPTURE}
        flow = EndpointFlow.CAPTURE if capture else EndpointFlow.RENDER
        native = GUID.format(flow=1 if capture else 0, index=index)
        endpoint_id = f"windows-mmdevice:v1:{flow.value}:{native}"
        result[role] = AudioEndpointRef(endpoint_id, f"Device {index}", flow, "WASAPI", index)
    return result


@pytest.fixture
def window(tmp_path, spies, monkeypatch):  # noqa: F811
    monkeypatch.setattr(bridge_tests, "mapping", native_mapping)
    window = bridge_tests.build_call_bridge_window(tmp_path, monkeypatch)
    window.activateWindow()
    yield window
    window.stop_call_bridge()
    window.stop_listening()
    window.close()


@pytest.fixture
def no_network(monkeypatch):
    attempts: list[object] = []

    def refuse(*args, **_kwargs):
        attempts.append(args)
        raise AssertionError("network access")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    return attempts


def run_sessions(window, spies) -> None:  # noqa: F811
    """A Conversation turn and a Call Bridge session, then a stale saved endpoint ID."""
    start(window)
    submit(window, spies, transcript("Guten Tag, geheimer Satz", "de"))
    assert wait_until(lambda: len(window.history) == 1)
    window.stop_listening()
    bridge_tests.assign(window)
    click(window.call_bridge_panel.start_button)
    assert wait_until(lambda: window.call_bridge_controller is not None)
    window.stop_call_bridge()
    window.show_error(
        f"Configured render endpoint is not available: {STALE_ID}", WorkspaceId.CALL_BRIDGE
    )
    window.diagnostics.record(
        "project", f"Settings file: {Path.cwd() / 'config' / 'settings.local.json'}"
    )


def save_to(monkeypatch, path) -> None:
    from PySide6.QtWidgets import QFileDialog

    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", staticmethod(lambda *_a: (str(path) if path else "", ""))
    )


def assert_redacted(window, text: str) -> None:
    assert text.strip()
    for turn in window.history:
        assert turn.source_text not in text and turn.translated_text not in text
    assert "geheimer" not in text
    assert not ABSOLUTE_PATH.search(text), text
    assert not ENDPOINT_ID.search(text), text
    user = getpass.getuser()
    assert not re.search(rf"(?<!\w){re.escape(user)}(?!\w)", text, re.IGNORECASE), text
    assert str(Path.home()) not in text


def banner_title(window) -> str:
    banner = window.banners[SETTINGS]
    return banner.title_label.text() if banner.isVisible() else ""


def test_ac27_export_failure_then_export_writes_a_redacted_file(
    window,
    spies,  # noqa: F811
    monkeypatch,
    tmp_path,
    no_network,
) -> None:
    run_sessions(window, spies)
    window.show_workspace(SETTINGS)
    view = window.settings.diagnostics_view
    entries = len(window.diagnostics.entries())

    save_to(monkeypatch, tmp_path / "read-only-folder" / "diagnostics.txt")  # cannot be written
    click(view.export_button)
    title = banner_title(window)
    assert title.startswith("Warning: Export failed: ") and "saved" not in title.lower()
    # The reason is redacted: no absolute path, not even the folder names (wave-1 B5).
    assert not ABSOLUTE_PATH.search(title), title
    assert "read-only-folder" not in title and tmp_path.name not in title
    assert len(window.diagnostics.entries()) > entries  # the log is kept (and grew)
    assert window.focusWidget() is view.export_button

    target = tmp_path / "diagnostics-E10.txt"
    save_to(monkeypatch, target)
    click(view.export_button)
    exported = target.read_text(encoding="utf-8")
    assert_redacted(window, exported)
    assert "<endpoint-" in exported and "<path>/" in exported  # the IDs and paths were there
    assert "diagnostics.txt" in exported  # the failed export is in the log, redacted
    assert banner_title(window) == "Information: Diagnostics saved as 'diagnostics-E10.txt'."
    assert view.history_text.toPlainText() == window.diagnostics.export_text()
    assert no_network == []


def test_ac27_copy_puts_the_same_redacted_text_on_the_clipboard(window, spies, no_network) -> None:  # noqa: F811
    from PySide6.QtWidgets import QApplication

    run_sessions(window, spies)
    window.show_workspace(SETTINGS)
    QApplication.clipboard().setText("before")

    click(window.settings.diagnostics_view.copy_button)

    copied = QApplication.clipboard().text()
    assert copied != "before"
    assert_redacted(window, copied)
    assert banner_title(window) == "Information: Diagnostics copied to the clipboard."
    assert no_network == []


def test_ac27_cancel_keeps_the_log_and_never_says_saved(window, monkeypatch, tmp_path) -> None:
    window.show_error("Something failed")
    window.show_workspace(SETTINGS)
    view = window.settings.diagnostics_view
    before = window.diagnostics.entries()
    save_to(monkeypatch, None)  # the dialog is cancelled

    click(view.export_button)

    assert banner_title(window) == (
        "Information: Export cancelled. Nothing was written; the log is kept."
    )
    assert window.diagnostics.entries()[: len(before)] == before  # nothing was cleared
    assert "conversation.error: Something failed" in view.history_text.toPlainText()
    assert window.focusWidget() is view.export_button
    assert list(tmp_path.glob("*.txt")) == []


def test_the_history_is_empty_until_something_is_recorded(window) -> None:
    window.show_workspace(SETTINGS)
    view = window.settings.diagnostics_view
    assert view.history_text.placeholderText() == "Nothing recorded yet."
    assert view.history_text.accessibleName() == "Notice history"
    assert (view.copy_button.text(), view.export_button.text()) == ("Copy", "Export…")
