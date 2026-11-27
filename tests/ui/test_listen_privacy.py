"""CAP-0170 WI-08 (AC-27, AC-28): no speech text leaves the Listen page, and no network.

AC-27 Integration: sentinel texts run through a full Listen flow (done rows, a failed row
whose error message holds a sentinel, Copy, Export, a diagnostics export); the log records,
the Diagnostics export and every posted notice contain none of them. AC-28: with sockets
blocked a listening session and a transcript export attempt no connection and start no pack
download; a static check finds no network module in ``lianiq/listen/`` or the Listen page.
"""
# ruff: noqa: F811 - the fixtures are imported

from __future__ import annotations

import ast
import logging
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from lianiq.listen.lifecycle import ListenPhase
from lianiq.listen.transcript import SegmentState
from lianiq.ui.shell.workspaces import WorkspaceId
from lianiq.ui.transcript import actions
from tests._spy_window import spies  # noqa: F401 - the fixture
from tests.meeting.test_controller_privacy import static_findings
from tests.packs.conftest import network_attempts  # noqa: F401 - the socket guard
from tests.ui._language_packs_helpers import wait_until
from tests.ui._listen_helpers import listen_window, phase_is, speak, start, states

ROOT = Path(__file__).resolve().parents[2] / "lianiq"
LISTEN_FILES = sorted((ROOT / "listen").glob("*.py")) + sorted(
    (ROOT / "ui" / "workspaces").glob("listen*.py")
)
LISTEN_FILES += sorted((ROOT / "transcript").glob("*.py"))  # the shared turn log and view
LISTEN_FILES += sorted((ROOT / "ui" / "transcript").glob("*.py"))
SENTINELS = ("Zebraquark 4711.", "Mondfisch Orakel 0815.")
LEAK = "Geheimnis Kobold 1234"
NETWORK = {"socket", "ssl", "urllib", "http", "requests", "httpx", "aiohttp", "ftplib"}
NETWORK |= {"lianiq.packs.sources", "lianiq.packs.transfer", "huggingface_hub"}


@pytest.fixture
def window(tmp_path, monkeypatch, spies):
    window = listen_window(tmp_path, monkeypatch)
    yield window
    window.listen.shutdown()
    window.close()


def save_as(monkeypatch, path: Path) -> None:
    monkeypatch.setattr(actions.QFileDialog, "getSaveFileName", lambda *a, **k: (str(path), ""))


def run_flow(window, spies, monkeypatch, tmp_path) -> Path:
    """Two done rows, one failed row (its error names a sentinel), Copy and Export."""
    start(window)
    translate = spies.translator.translate

    def leaky(text, edge, context=()):
        if LEAK in text:
            raise RuntimeError(f"cannot translate {text}")
        return translate(text, edge, context)

    spies.translator.translate = leaky
    speak(window, spies, SENTINELS[0], LEAK, SENTINELS[1])
    expected = [SegmentState.DONE, SegmentState.FAILED, SegmentState.DONE]
    assert wait_until(lambda: states(window) == expected)
    window.stop_active_session()
    assert phase_is(window, ListenPhase.IDLE)
    window.listen.copy_button.click()
    target = tmp_path / "listen.txt"
    save_as(monkeypatch, target)
    window.listen.export_button.click()
    return target


def secrets(window) -> list[str]:
    found = [*SENTINELS, LEAK, "Zebraquark", "Mondfisch", "Kobold"]
    for row in window.listen.controller.transcript.rows:
        if row.result is not None:
            found.append(row.result.translated_text)
    return found


def test_ac27_sentinels_reach_no_log_diagnostics_or_notice(
    window, spies, monkeypatch, tmp_path, caplog
) -> None:
    caplog.set_level(logging.DEBUG)
    exported = run_flow(window, spies, monkeypatch, tmp_path)
    assert SENTINELS[0] in exported.read_text(encoding="utf-8")  # the explicit export only
    hidden = secrets(window)

    diagnostics = window.diagnostics.export_text()
    notices = [f"{n.title}\n{n.detail}" for n in window.notices.history()]
    assert any(n.key == "listen.failed" for n in window.notices.history())
    records = [record.getMessage() for record in caplog.records]
    for text in (diagnostics, *notices, *records):
        assert not [secret for secret in hidden if secret and secret in text], text


def test_ac27_static_check_listen_code_logs_no_text() -> None:
    assert ROOT / "listen" / "controller.py" in LISTEN_FILES
    findings = [f for path in LISTEN_FILES for f in static_findings(path) if "imports" not in f]
    assert findings == []


def test_ac28_listening_and_export_attempt_no_connection_or_download(
    window, spies, monkeypatch, tmp_path, network_attempts
) -> None:
    run_flow(window, spies, monkeypatch, tmp_path)
    assert network_attempts == []
    assert window.language_packs.runner.current is None  # no pack job was started
    assert window.notices.get("listen-and-translate.export-failed") is None
    assert window.current_workspace() is WorkspaceId.LISTEN


def network_imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            modules = [node.module or ""]
        else:
            continue
        for module in modules:
            if module in NETWORK or module.split(".")[0] in NETWORK:
                found.append(f"{path.name}:{node.lineno} imports {module}")
    return found


def test_ac28_static_check_no_network_module_in_the_listen_code(tmp_path) -> None:
    assert [finding for path in LISTEN_FILES for finding in network_imports(path)] == []
    bad = tmp_path / "bad.py"
    bad.write_text("import urllib.request\nfrom lianiq.packs.sources import X\n", "utf-8")
    assert len(network_imports(bad)) == 2
