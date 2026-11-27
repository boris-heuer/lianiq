"""CAP-0170 WI-06 (AC-04, AC-26): Language packs and the Listen page.

Through the real ``MainWindow`` (offscreen, not provisioned) with the built-in catalog, the
fake ``Transport`` of CAP-0171 and the WI-02 ``FakeCapture``: a missing pack blocks Start
with **Open Language packs**, a pack job makes Start available without a restart, and the
packs of a running session cannot be updated or removed.
"""
# ruff: noqa: F811 - the fixtures are imported

from __future__ import annotations

import itertools
from datetime import UTC, datetime

import pytest

pytest.importorskip("PySide6")

from lianiq.listen.lifecycle import ListenPhase
from lianiq.packs.catalog import PackCatalog
from lianiq.packs.sources import DownloadSource
from lianiq.ui import strings
from lianiq.ui.shell.workspaces import WorkspaceId, label
from lianiq.ui.workspaces.listen import ListenWorkspace
from tests._spy_window import build_window, spies  # noqa: F401
from tests.listen._listen_helpers import FakeCapture
from tests.packs.conftest import network_attempts  # noqa: F401
from tests.ui._language_packs_helpers import (  # noqa: F401
    MT,
    STT,
    default_paths,
    download,
    open_page,
    packs_shaped,
    wait_until,
)

LISTEN = WorkspaceId.LISTEN
MT_BACK = "mt-zh-hans-de"


@pytest.fixture
def window(tmp_path, spies, monkeypatch, shaped):
    captures: list[FakeCapture] = []

    def capture(self, on_utterance, on_error) -> FakeCapture:
        captures.append(FakeCapture(on_utterance, on_error))
        return captures[-1]

    monkeypatch.setattr(ListenWorkspace, "_capture", capture)
    project = tmp_path / "project"
    project.mkdir()
    window = build_window(project, monkeypatch, provisioned=False, configure=default_paths)
    window.listen_captures = captures
    packs = window.language_packs
    packs.transport = shaped[1]
    packs.runner._monotonic = itertools.count().__next__  # every progress call passes
    yield window
    window.listen.shutdown()
    shaped[3].set()
    packs.runner.cancel()
    assert wait_until(lambda: packs.runner.current is None)
    window.close()


def show_listen(window) -> ListenWorkspace:
    assert window.show_workspace(LISTEN)
    return window.listen


def install(window, *pack_ids: str) -> None:
    page = open_page(window)
    for pack_id in pack_ids:
        download(page, pack_id)


def test_ac04_a_missing_pack_blocks_start_and_links_to_the_packs(window) -> None:
    for edge in window.config.translation.edges.values():
        edge.model_path = "models/absent"  # configured, files missing
    window.refresh_readiness()
    page = show_listen(window)
    assert not page.start_button.isEnabled()
    assert page.readiness_label.text() == (  # row-3 order: recognition, then translation
        "Not available: missing speech recognition German, "
        "translation German → Mandarin (Simplified)"
    )
    assert page.open_packs_button.isVisible()
    page.open_packs_button.click()
    assert window.current_workspace() is WorkspaceId.LANGUAGE_PACKS


def test_ac04_an_unconfigured_edge_no_pack_covers_is_unsupported(window) -> None:
    install(window, STT, MT)  # German → Mandarin is ready: the no-pack hint does not apply
    del window.config.translation.edges["zh-Hans>de"]
    window.refresh_readiness()
    packs = window.language_packs
    packs.packs = PackCatalog(tuple(p for p in packs.packs.packs() if p.id != MT_BACK))
    page = show_listen(window)
    page.swap_button.click()  # Mandarin (Simplified) → German
    assert page.readiness_label.text() == strings.LISTEN_UNSUPPORTED.format(
        source="Mandarin (Simplified)", target="German"
    )
    assert not page.open_packs_button.isVisible() and not page.start_button.isEnabled()


def test_ac26_a_validated_pack_enables_start_without_restart(window) -> None:
    page = show_listen(window)
    assert not page.start_button.isEnabled()
    install(window, STT, MT)  # German → Mandarin (Simplified) needs only these two
    page = show_listen(window)
    assert wait_until(page.start_button.isEnabled)
    assert page.readiness_label.text() == ""
    window.start_current_page()  # F8 on the Listen page
    assert wait_until(lambda: page.controller.phase is ListenPhase.LISTENING)


def test_ac26_the_session_packs_cannot_be_updated_or_removed(window) -> None:
    install(window, STT, MT)
    page = show_listen(window)
    window.start_current_page()  # F8 on the Listen page
    assert wait_until(lambda: page.controller.phase is ListenPhase.LISTENING)
    packs = window.language_packs
    in_use = strings.PACK_IN_USE.format(mode=label(LISTEN))
    for pack_id, operation in ((STT, "remove"), (MT, "update")):
        source = None if operation == "remove" else DownloadSource(packs.transport)
        assert not packs.start(pack_id, operation, source, datetime.now(UTC))
        assert packs.rows[pack_id].message_label.text() == in_use
    window.stop_active_session()
    assert wait_until(lambda: page.controller.phase is ListenPhase.IDLE)
