"""Fixtures and helpers of the Language packs workspace tests (CAP-0171 WI-04).

The window loads the built-in catalog shaped with a few bytes per file (``builtin_shaped``)
and downloads through the fake ``Transport`` of ``tests/packs``; ``network_attempts`` is
the socket guard of ``tests/packs``.
"""

from __future__ import annotations

import itertools
import json
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packs"))

from _install_fixtures import FakeTransport, builtin_shaped, pack_folder  # noqa: F401

from lianiq.config import AppConfig
from lianiq.ui import strings
from lianiq.ui.shell.workspaces import WorkspaceId
from lianiq.ui.workspaces import language_packs as packs_module
from tests._spy_window import build_window, spies  # noqa: F401
from tests.packs.conftest import network_attempts  # noqa: F401

STT, MT = "stt-faster-whisper-small", "mt-de-zh-hans"
VOICE_DE = "tts-de-thorsten-medium"
ALL = (STT, MT, "mt-zh-hans-de", "mt-en-zh-hans", "mt-zh-hans-en", VOICE_DE)
ALL += ("tts-zh-hans-aishell3", "tts-en-us-ljspeech-high")
PLENTY = 10**12


def wait_until(condition, timeout: float = 5.0) -> bool:
    """Process Qt events and sleep: ``QTest.qWait`` keeps the GIL, which starves the pack
    worker threads on every file system call."""
    from PySide6.QtWidgets import QApplication

    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.01)
    QApplication.processEvents()
    return condition()


def default_paths(config: AppConfig, _root: Path) -> None:
    """The repository default model paths, which are the pack roots (no custom path)."""
    fresh = AppConfig()
    config.speech_to_text.model_path = fresh.speech_to_text.model_path
    config.translation.edges = fresh.translation.edges
    config.tts.voices = fresh.tts.voices
    config.tts.engines = fresh.tts.engines


@pytest.fixture(name="shaped")
def packs_shaped(tmp_path, monkeypatch, network_attempts):  # noqa: F811
    catalog, payloads, contents = builtin_shaped(tmp_path / "catalog")
    monkeypatch.setattr(
        packs_module, "BUILTIN_CATALOG_PATH", tmp_path / "catalog" / "builtin-shaped.json"
    )
    monkeypatch.setattr(packs_module, "free_bytes", lambda _folder: PLENTY)
    gate = threading.Event()
    gate.set()
    transport = FakeTransport(payloads, on_read=lambda _url, _pos: gate.wait(5))
    return catalog, transport, contents, gate


@pytest.fixture(name="network")
def packs_network(network_attempts):  # noqa: F811
    """The socket guard's record of network attempts (empty unless something connected)."""
    return network_attempts


@pytest.fixture(name="window")
def packs_window(tmp_path, spies, monkeypatch, shaped):  # noqa: F811
    project = tmp_path / "project"
    project.mkdir()
    window = build_window(project, monkeypatch, provisioned=False, configure=default_paths)
    page = window.language_packs
    page.transport = shaped[1]
    page.runner._monotonic = itertools.count().__next__  # every progress call passes
    yield window
    shaped[3].set()
    page.runner.cancel()
    assert wait_until(lambda: page.runner.current is None)
    window.close()


def open_page(window):
    window.navigation.buttons[WorkspaceId.LANGUAGE_PACKS].click()
    assert window.current_workspace() is WorkspaceId.LANGUAGE_PACKS
    page = window.language_packs
    assert wait_until(lambda: len(page.statuses) == len(ALL))
    return page


def state(page, pack_id: str) -> str:
    return page.rows[pack_id].state_text


def download(page, pack_id: str, *, wait: bool = True):
    row = page.rows[pack_id]
    row.primary_button.click()
    dialog = page.details
    assert not dialog.download_button.isEnabled()  # AC-07: the licence gate
    dialog.licence_box.setChecked(True)
    dialog.download_button.click()
    if wait:
        assert wait_until(lambda: state(page, pack_id) == strings.PACK_STATE_VALIDATED)
    return row


def manifest(window) -> dict:
    return json.loads((window.language_packs.manifest_path).read_text(encoding="utf-8"))


def manifest_or_empty(window) -> dict:
    path = window.language_packs.manifest_path
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
