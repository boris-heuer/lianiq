"""CAP-0172 WI-07: privacy and offline guards of Text translation (AC-33, AC-34).

AC-33 (Integration): the e2e plan's sentinel text D-05 runs through the full flow (Translate,
a failing and a stopped playback, Settings › Diagnostics › **Export…**, close with settings
saved); neither the log records, the notices, the export nor any written file (the saved
``settings.local.json`` included) holds it, and after a restart *Source text* is empty.
AC-34 (Integration, socket guard): translating and playing attempt no connection and start
no download. AC-34 (Static check): no Text translation module imports a network module or
the pack download path, and none logs a text (the CAP-0177 privacy check, reused).
"""

from __future__ import annotations

import ast
import logging
import socket
import urllib.request
from pathlib import Path

import pytest

import lianiq.config as config_module
from lianiq.packs.sources import HttpsTransport
from lianiq.ui.notice_catalog_base import PLAYBACK_FAILED
from lianiq.ui.shell.workspaces import WorkspaceId
from tests._spy_window import build_window, spies  # noqa: F401 - pytest fixture
from tests.meeting.test_controller_privacy import static_findings
from tests.ui._language_helpers import wait_until
from tests.ui.test_main_window_session import click
from tests.ui.test_shell_diagnostics import save_to
from tests.ui.test_text_translation_playback import (  # noqa: F401 - pytest fixtures
    idle,
    page,
    player,
    playing,
    translated,
)

ROOT = Path(__file__).resolve().parents[2]
SENTINEL = "Lianiq sentinel QX7 Textprobe."  # e2e plan D-05
NEEDLES = ("QX7", "Textprobe")
NETWORK = {"socket", "ssl", "urllib", "http", "requests", "httpx", "huggingface_hub"}
DOWNLOAD = {"lianiq.packs.sources", "lianiq.packs.transfer", "lianiq.packs.import_source"}
MODULES = (
    *sorted((ROOT / "lianiq" / "text_translation").glob("*.py")),
    ROOT / "lianiq" / "audio" / "playback_control.py",
    *sorted((ROOT / "lianiq" / "ui" / "workspaces").glob("text_translation*.py")),
)


def leaks(text: str) -> bool:
    return any(needle in text for needle in NEEDLES)


def test_ac33_the_sentinel_never_leaves_the_page_and_a_restart_shows_no_draft(
    page,  # noqa: F811
    player,  # noqa: F811
    tmp_path,
    monkeypatch,
    caplog,
) -> None:
    caplog.set_level(logging.DEBUG)
    window = page.host
    saved = tmp_path / "config" / "settings.local.json"
    monkeypatch.setattr(config_module, "LOCAL_CONFIG_PATH", saved)
    window.persist_settings = True
    translated(page, SENTINEL)
    player.error = OSError(SENTINEL)  # the exception text must not reach the notice
    page.play_button.click()
    assert wait_until(idle(page)) and window.notices.get(PLAYBACK_FAILED) is not None
    player.error = None
    page.play_button.click()
    assert wait_until(playing(page))
    page.play_button.click()  # Stop
    assert wait_until(idle(page))

    window.show_workspace(WorkspaceId.SETTINGS)
    export = tmp_path / "diag.txt"
    save_to(monkeypatch, export)
    click(window.settings.diagnostics_view.export_button)
    assert export.is_file()
    for notice in window.notices.history():
        assert not leaks(f"{notice.title} {notice.detail} {notice.source} {notice.continues}")
    assert not leaks(window.diagnostics.export_text())
    window.close()

    assert saved.is_file()  # the close wrote the settings
    assert [record.getMessage() for record in caplog.records if leaks(record.getMessage())] == []
    settings = sorted((ROOT / "config").glob("settings*.json"))
    files = [path for path in [*tmp_path.rglob("*"), *settings] if path.is_file()]
    assert [path.name for path in files if b"QX7" in path.read_bytes()] == []

    restarted = build_window(tmp_path / "restart", monkeypatch)
    try:
        restarted.navigation.select(WorkspaceId.TEXT_TRANSLATION)
        assert restarted.text_translation.source_edit.toPlainText() == ""
        assert restarted.text_translation.result_edit.toPlainText() == ""
    finally:
        restarted.close()


@pytest.fixture
def offline(monkeypatch) -> list[tuple]:
    attempts: list[tuple] = []

    def refuse(*args, **_kwargs):
        attempts.append(args)
        raise AssertionError("network access")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    monkeypatch.setattr(urllib.request, "urlopen", refuse)
    monkeypatch.setattr(HttpsTransport, "open", refuse)
    return attempts


def test_ac34_translating_and_playing_attempt_no_connection(
    page,  # noqa: F811
    player,  # noqa: F811
    offline,
    monkeypatch,
) -> None:
    jobs: list[tuple] = []
    monkeypatch.setattr(page.host.language_packs, "start", lambda *args: jobs.append(args))
    translated(page, "Guten Morgen. Heute testen wir die Textübersetzung.")
    page.play_button.click()
    assert wait_until(playing(page))
    page.play_button.click()
    assert wait_until(idle(page))
    assert offline == [] and player.devices  # played, offline
    assert jobs == []  # no pack download or import started


def imported(path: Path) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def test_ac34_static_check_no_network_or_download_import() -> None:
    assert len(MODULES) >= 10
    findings = [
        f"{path.name}: {module}"
        for path in MODULES
        for module in sorted(imported(path))
        if module.split(".")[0] in NETWORK or module in DOWNLOAD
    ]
    assert findings == []


def test_ac33_static_check_no_text_in_log_calls() -> None:
    assert [finding for path in MODULES for finding in static_findings(path)] == []
