"""CAP-0172 WI-05: Text translation with the CAP-0171 pack catalog and post-job refresh.

AC-08, AC-09 (regression with a real ``PackCatalog``), AC-10, AC-28 and AC-32 through the
real ``MainWindow`` (offscreen, spy adapters); AC-32 downloads through the fake ``Transport``.
"""

from __future__ import annotations

import itertools
import shutil

import pytest

from lianiq.packs.catalog import PackCatalog
from lianiq.text_translation.readiness import TranslateBlock
from lianiq.ui import notice_catalog_text as notices
from lianiq.ui import strings
from lianiq.ui.shell.workspaces import WorkspaceId
from tests._spy_window import build_window, spies  # noqa: F401 - pytest fixture
from tests.packs.conftest import network_attempts  # noqa: F401
from tests.ui._language_packs_helpers import (  # noqa: F401 - the fixtures are imported
    MT,
    default_paths,
    download,
    open_page,
    packs_network,
    packs_shaped,
    wait_until,
)

TEXT = WorkspaceId.TEXT_TRANSLATION
PACKS = WorkspaceId.LANGUAGE_PACKS


def text_page(window):
    window.navigation.select(TEXT)
    return window.text_translation


def type_text(workspace, text: str) -> None:
    workspace.source_edit.setFocus()
    workspace.source_edit.insertPlainText(text)


def shown(widget) -> bool:
    return not widget.isHidden()


def without_edges(*keys):
    def configure(config, _root):
        for key in keys:
            del config.translation.edges[key]

    return configure


def test_ac09_no_edge_and_no_catalog_pack_stays_unsupported(tmp_path, spies, monkeypatch) -> None:  # noqa: F811
    window = build_window(
        tmp_path, monkeypatch, provisioned=False, configure=without_edges("zh-Hans>de")
    )
    try:
        real = window.language_packs.packs
        window.language_packs.packs = PackCatalog(
            tuple(pack for pack in real.packs() if pack.id != "mt-zh-hans-de")
        )
        workspace = text_page(window)
        workspace.swap_button.click()
        type_text(workspace, "你好。")
        assert workspace.controller.readiness.translate is TranslateBlock.UNSUPPORTED
        assert workspace.readiness_label.text() == (
            "Translation from Mandarin (Simplified) to German is not supported."
        )
        assert not shown(workspace.readiness_packs_button)  # no link
        assert not workspace.translate_button.isEnabled()
    finally:
        window.close()


def test_ac08_a_catalog_pack_not_installed_names_it_and_links(tmp_path, spies, monkeypatch) -> None:  # noqa: F811
    window = build_window(
        tmp_path, monkeypatch, provisioned=False, configure=without_edges("de>zh-Hans")
    )
    try:
        workspace = text_page(window)
        type_text(workspace, "Hallo.")
        assert workspace.controller.readiness.translate is TranslateBlock.PACK_MISSING
        assert "translation German → Mandarin (Simplified)" in workspace.readiness_label.text()
        assert not workspace.translate_button.isEnabled()
        button = workspace.readiness_packs_button
        assert shown(button) and button.text() == strings.PACKS_OPEN
        assert not shown(workspace.no_pack_button)  # the reverse pack is installed
        button.click()
        assert window.current_workspace() is PACKS
    finally:
        window.close()


def test_ac10_no_translation_pack_at_all(tmp_path, spies, monkeypatch) -> None:  # noqa: F811
    window = build_window(
        tmp_path,
        monkeypatch,
        provisioned=False,
        configure=without_edges("de>zh-Hans", "zh-Hans>de"),
    )
    try:
        workspace = text_page(window)
        assert workspace.result_edit.placeholderText() == strings.TEXT_NO_PACK_HINT
        assert shown(workspace.no_pack_button)
        assert workspace.no_pack_button.text() == strings.PACKS_OPEN
        type_text(workspace, "Hallo.")
        assert not workspace.play_button.isEnabled()
        assert not workspace.copy_translation_button.isEnabled()
        assert workspace.copy_source_button.isEnabled()
        workspace.no_pack_button.click()
        assert window.current_workspace() is PACKS
    finally:
        window.close()


def test_ac28_a_missing_voice_links_the_packs_and_keeps_the_translation(
    tmp_path,
    spies,  # noqa: F811
    monkeypatch,
) -> None:
    window = build_window(tmp_path, monkeypatch, provisioned=False)  # no voices on disk
    try:
        workspace = text_page(window)
        type_text(workspace, "Hallo.")
        workspace.translate_button.click()
        assert wait_until(lambda: workspace.controller.draft.current_result() is not None)
        assert not workspace.play_button.isEnabled()
        assert workspace.play_hint.text() == (
            "Play translation needs the Mandarin (Simplified) voice."
        )
        assert shown(workspace.voice_packs_button)
        translation = workspace.result_edit.toPlainText()
        workspace.voice_packs_button.click()
        assert window.current_workspace() is PACKS
        assert text_page(window).result_edit.toPlainText() == translation != ""
    finally:
        window.close()


def test_the_playback_failed_notice_also_opens_language_packs() -> None:
    opened: list[str] = []
    notice = notices.playback_failed(
        "x", "Text translation", lambda: opened.append("audio"), lambda: opened.append("packs")
    )
    assert [action.label for action in notice.actions] == [
        strings.TEXT_OPEN_AUDIO,
        strings.PACKS_OPEN,
    ]
    notice.actions[1].callback()
    assert opened == ["packs"]


@pytest.fixture(name="window")
def no_translation_window(tmp_path, spies, monkeypatch, shaped):  # noqa: F811
    """The Language packs window of CAP-0171 with no translation model on disk."""

    def configure(config, root):
        default_paths(config, root)
        for folder in (root / "models").glob("opus-mt-*"):
            shutil.rmtree(folder)

    project = tmp_path / "project"
    project.mkdir()
    window = build_window(project, monkeypatch, provisioned=False, configure=configure)
    page = window.language_packs
    page.transport = shaped[1]
    page.runner._monotonic = itertools.count().__next__  # every progress call passes
    yield window
    page.runner.cancel()
    assert wait_until(lambda: page.runner.current is None)
    window.close()


def test_ac32_a_pack_job_makes_translate_ready_without_restart(window, spies) -> None:  # noqa: F811
    controller = window.text_translation.controller
    assert controller.readiness.translate is TranslateBlock.PACK_MISSING and controller.no_pack
    old = window.pipeline.text_translator()  # the adapter cached before the job
    page = open_page(window)
    download(page, MT)
    # The CAP-0171 refresh hook updates the page while Language packs is still shown.
    assert wait_until(lambda: controller.readiness.translate is TranslateBlock.NONE)
    assert not controller.no_pack
    workspace = text_page(window)
    assert workspace.result_edit.placeholderText() == strings.TEXT_RESULT_EMPTY
    type_text(workspace, "Hallo.")
    assert workspace.translate_button.isEnabled()
    workspace.translate_button.click()
    assert wait_until(lambda: controller.draft.current_result() is not None)
    assert spies.translator is not old  # the rebuilt adapter translated
