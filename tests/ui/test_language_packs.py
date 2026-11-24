"""CAP-0171 WI-04: the Language packs workspace through the real ``MainWindow`` (offscreen).

The fake ``Transport`` and the socket guard of ``tests/packs`` are on (see
``_language_packs_helpers``), so no test touches the network. AC-07, AC-08, AC-09, AC-10,
AC-12, AC-13, AC-33, the empty-page half of AC-34 and the contract §8 protection fallback.
"""

from __future__ import annotations

from datetime import UTC, datetime

from lianiq.packs.jobs import JobPhase
from lianiq.packs.sources import DownloadSource
from lianiq.ui import strings
from lianiq.ui.shell.workspaces import WorkspaceId
from lianiq.ui.workspaces import language_packs as packs_module
from lianiq.ui.workspaces import pack_details_dialog as dialog_module
from lianiq.ui.workspaces.language_packs_rows import progress_text
from tests._spy_window import spies  # noqa: F401
from tests.packs.conftest import network_attempts  # noqa: F401
from tests.ui._language_packs_helpers import (  # noqa: F401 - the fixtures are imported
    ALL,
    MT,
    PLENTY,
    STT,
    VOICE_DE,
    download,
    manifest,
    manifest_or_empty,
    open_page,
    pack_folder,
    packs_network,
    packs_shaped,
    packs_window,
    state,
    wait_until,
)


def test_ac34_the_empty_page_lists_every_pack_downloadable_and_planned_collapsed(
    window,
    shaped,
    network,
) -> None:
    page = open_page(window)
    assert window.navigation.buttons[WorkspaceId.LANGUAGE_PACKS].isEnabled()
    assert {pack_id: state(page, pack_id) for pack_id in ALL} == dict.fromkeys(
        ALL, strings.PACK_STATE_DOWNLOADABLE
    )
    assert all(page.rows[p].primary_button.text() == strings.PACK_GET for p in ALL)
    assert page.layout.empty_hint.isVisible()
    assert page.layout.empty_hint.text() == strings.PACK_EMPTY_HINT
    assert page.layout.planned_names == ["Spanish", "French"]
    assert not page.layout.planned_list.isVisible()  # collapsed
    assert page.layout.folder_label.text().startswith("Models folder: ")
    row = page.rows[MT]
    assert row.accessibleName() == f"{row.name}, {strings.PACK_STATE_DOWNLOADABLE}"
    assert shaped[1].opened == [] and network == []  # nothing connects before Download


def test_ac07_ac08_licence_gate_then_download_to_validated_with_progress(window) -> None:
    page = open_page(window)
    events = []
    window.bridge.packs_event.connect(events.append)
    page.rows[MT].primary_button.click()
    dialog = page.details
    texts = [label.text() for label in dialog.values.values()]
    assert "Helsinki-NLP" in texts[0] and "Apache-2.0" in texts
    assert page.packs.get(MT).files[0].sha256 in dialog.integrity.toPlainText()
    assert not dialog.integrity.isVisible() and not dialog.import_button.isEnabled()
    dialog.licence_box.setChecked(True)
    assert dialog.download_button.isEnabled() and dialog.import_button.isEnabled()
    dialog.download_button.click()

    assert wait_until(lambda: state(page, MT) == strings.PACK_STATE_VALIDATED)
    views = [event[1] for event in events if event[0] == "progress"]
    assert {view.phase for view in views} >= {JobPhase.TRANSFER, JobPhase.CHECK}
    transfer = next(v for v in views if v.phase is JobPhase.TRANSFER)
    assert " of " in progress_text(transfer) and "bytes" in progress_text(transfer)
    check = next(v for v in views if v.phase is JobPhase.CHECK)
    assert progress_text(check).startswith("Checking integrity… ")
    record = next(item for item in manifest(window)["packs"] if item["id"] == MT)
    assert record["source"] == "download" and record["licence_accepted_at"]
    assert not page.layout.empty_hint.isVisible()
    assert page.rows[MT].remove_button.isVisible()
    logged = [text for _, category, text in window.diagnostics.entries() if category == "packs"]
    assert logged == [f"pack_id={MT} version=1 operation=install state=succeeded"]


def test_ac09_cancel_returns_the_row_with_the_reason_and_retry(window, shaped) -> None:
    page = open_page(window)
    gate = shaped[3]
    gate.clear()
    row = download(page, MT, wait=False)
    assert wait_until(lambda: row.cancel_button.isVisible())
    assert row.state_text == strings.PACK_STATE_INSTALLING and row.progress.isVisible()
    row.cancel_button.click()
    gate.set()
    assert wait_until(lambda: row.message_label.text() == "Cancelled")
    assert wait_until(lambda: row.state_text == strings.PACK_STATE_DOWNLOADABLE)
    assert row.retry_button.isVisible() and not row.cancel_button.isVisible()
    assert "packs" not in manifest_or_empty(window)

    row.retry_button.click()  # the same download, licence already accepted
    assert wait_until(lambda: row.state_text == strings.PACK_STATE_VALIDATED)
    assert not row.message_label.isVisible()


def test_ac13_no_connection_names_the_host_with_import_and_retry(window, shaped) -> None:
    page = open_page(window)
    download(page, STT)  # an installed pack stays Validated
    transport = shaped[1]
    host = "huggingface.co"
    assert any(host in url for url in transport.payloads)
    transport.unavailable = frozenset({host})
    row = download(page, MT, wait=False)
    expected = strings.PACK_DOWNLOAD_UNAVAILABLE.format(host=host)
    assert wait_until(lambda: row.message_label.text() == expected)
    assert wait_until(lambda: row.state_text == strings.PACK_STATE_DOWNLOADABLE)
    assert row.import_button.isVisible() and row.retry_button.isVisible()
    assert state(page, STT) == strings.PACK_STATE_VALIDATED
    logged = [text for _, category, text in window.diagnostics.entries() if category == "packs"]
    assert logged[-1].endswith("state=failed error=ConnectionUnavailable")
    row.import_button.click()  # Import… opens the details dialog with its import menu
    assert page.details.pack.id == MT


def test_ac12_no_space_disables_the_dialog_and_stops_a_started_job(window, monkeypatch) -> None:
    page = open_page(window)
    monkeypatch.setattr(packs_module, "free_bytes", lambda _folder: 0)
    page.rows[MT].primary_button.click()
    dialog = page.details
    assert dialog.space_label.isVisible() and dialog.space_label.text().startswith(
        "Not enough disk space: "
    )
    dialog.licence_box.setChecked(True)
    assert not dialog.download_button.isEnabled() and not dialog.import_button.isEnabled()
    dialog.reject()

    monkeypatch.setattr(packs_module, "free_bytes", lambda _folder: PLENTY)
    page.rows[MT].primary_button.click()
    page.details.licence_box.setChecked(True)
    monkeypatch.setattr(packs_module, "free_bytes", lambda _folder: 0)  # drops before start
    page.details.download_button.click()
    row = page.rows[MT]
    assert row.message_label.text().startswith("Not enough disk space: ")
    assert row.state_text == strings.PACK_STATE_DOWNLOADABLE and page.runner.current is None
    assert not (window.language_packs.root / "models" / ".lianiq-staging").exists()


def test_remove_confirms_the_usages_and_returns_the_row_to_downloadable(
    window, monkeypatch
) -> None:
    page = open_page(window)
    for pack_id in (STT, MT, "mt-zh-hans-de"):
        download(page, pack_id)
    asked = []
    monkeypatch.setattr(packs_module, "confirm_remove", lambda _p, text: asked.append(text) or 1)
    page.rows[MT].remove_button.click()
    assert asked == [
        strings.PACK_REMOVE_CONFIRM.format(pack=page.packs.get(MT).model, usages="Conversation")
    ]
    assert wait_until(lambda: state(page, MT) == strings.PACK_STATE_DOWNLOADABLE)
    assert all(item["id"] != MT for item in manifest(window)["packs"])
    logged = [text for _, category, text in window.diagnostics.entries() if category == "packs"]
    assert logged[-1] == f"pack_id={MT} version=1 operation=remove state=succeeded"


def test_ac10_import_of_a_folder_makes_no_network_call(
    window,
    shaped,
    tmp_path,
    monkeypatch,
    network,
) -> None:
    page = open_page(window)
    pack = page.packs.get(VOICE_DE)
    folder = pack_folder(tmp_path / "usb" / "voice", pack, shaped[2][VOICE_DE])
    monkeypatch.setattr(dialog_module, "pick_folder", lambda _parent: folder)
    page.rows[VOICE_DE].primary_button.click()
    page.details.licence_box.setChecked(True)
    page.details.import_folder_action.trigger()
    assert wait_until(lambda: state(page, VOICE_DE) == strings.PACK_STATE_VALIDATED)
    record = next(item for item in manifest(window)["packs"] if item["id"] == VOICE_DE)
    assert record["source"] == "import"
    assert not (page.root / pack.root / "extra-notes.txt").exists()
    assert shaped[1].opened == [] and network == []


def test_ac33_a_running_job_disables_every_other_job_action_with_pack_busy(window, shaped) -> None:
    page = open_page(window)
    shaped[3].clear()
    download(page, MT, wait=False)
    assert wait_until(lambda: page.rows[MT].cancel_button.isVisible())
    other = page.rows[STT].primary_button
    assert not other.isEnabled() and other.toolTip() == strings.PACK_BUSY
    source = DownloadSource(page.transport)
    assert not page.start(STT, "install", source, datetime.now(UTC))  # JobBusy from the runner
    assert page.rows[STT].message_label.text() == strings.PACK_BUSY
    shaped[3].set()
    assert wait_until(lambda: state(page, MT) == strings.PACK_STATE_VALIDATED)
    assert page.rows[STT].primary_button.isEnabled()


def test_an_unbound_running_session_protects_installed_packs_but_allows_new_ones(
    window, monkeypatch
) -> None:
    page = open_page(window)
    download(page, MT)
    monkeypatch.setattr(packs_module, "confirm_remove", lambda _parent, _text: True)
    window.session_owner.request_start(WorkspaceId.CONVERSATION)  # no bound usage yet
    page.rows[MT].remove_button.click()
    assert page.rows[MT].message_label.text() == "Stop the running Conversation session first"
    assert state(page, MT) == strings.PACK_STATE_VALIDATED
    download(page, VOICE_DE)  # not installed: Get… still works during the session
    window.session_owner.stop()


def test_before_the_first_snapshot_rows_have_no_actions_and_the_guard_protects_all(
    window,
) -> None:
    page = window.language_packs  # the page was never shown: no status snapshot yet
    row = page.rows[MT]
    assert row.state_text == strings.PACK_STATE_CHECKING and not row.primary_button.isVisible()
    assert page.installed_ids() is None
    window.session_owner.request_start(WorkspaceId.CONVERSATION)  # no bound usage yet
    assert not page.start(MT, "install", DownloadSource(page.transport), datetime.now(UTC))
    assert row.message_label.text() == "Stop the running Conversation session first"
    window.session_owner.stop()


def test_a_status_failure_shows_unknown_rows_and_keeps_the_fail_safe(window, monkeypatch) -> None:
    def broken(*_args):
        raise OSError("disk gone")

    monkeypatch.setattr(packs_module, "readiness_pack_files", broken)
    window.navigation.buttons[WorkspaceId.LANGUAGE_PACKS].click()
    page = window.language_packs
    assert wait_until(lambda: page.layout.status_message.isVisible())
    assert page.layout.status_message.text() == strings.PACKS_STATUS_FAILED
    assert state(page, MT) == strings.PACK_STATE_UNKNOWN
    assert not page.rows[MT].primary_button.isVisible() and page.installed_ids() is None


def test_a_failed_row_offers_download_again_and_import(window) -> None:
    page = open_page(window)
    download(page, MT)
    pack = page.packs.get(MT)
    (page.root / pack.root / pack.files[0].path).unlink()
    page.refresh()
    assert wait_until(lambda: state(page, MT) == strings.PACK_STATE_FAILED)
    row = page.rows[MT]
    assert row.primary_button.text() == strings.PACK_REDOWNLOAD and row.primary_button.isVisible()
    assert row.import_button.isVisible()
