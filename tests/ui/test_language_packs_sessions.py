"""CAP-0171 WI-05: packs of the active session, readiness refresh and the no-pair notice.

Through the real ``MainWindow`` (offscreen) with the fake ``Transport`` and spy adapters:
AC-15..AC-20, the Settings-link half of AC-34 and the notice half of AC-31. Pack jobs run
on worker threads, so the sleeping ``wait_until`` of ``_language_packs_helpers`` is used.
"""

from __future__ import annotations

from datetime import UTC, datetime

from lianiq.languages.capabilities import CapabilityCatalog, ReadinessProbe
from lianiq.languages.modes import OutputKind
from lianiq.languages.registry import LanguageId
from lianiq.packs.jobs import CancelToken
from lianiq.packs.protection import packs_in_use
from lianiq.packs.sources import DownloadSource
from lianiq.ui import notice_catalog as catalog
from lianiq.ui import strings
from lianiq.ui.shell.session_owner import SessionState
from lianiq.ui.shell.workspaces import WorkspaceId, label
from lianiq.ui.workspaces import language_packs as packs_module
from tests._spy_window import spies  # noqa: F401
from tests.packs.conftest import network_attempts  # noqa: F401
from tests.ui._call_bridge_window import assign, build_call_bridge_window
from tests.ui._language_packs_helpers import (  # noqa: F401 - the fixtures are imported
    MT,
    STT,
    VOICE_DE,
    download,
    open_page,
    packs_network,
    packs_shaped,
    packs_window,
    state,
    wait_until,
)
from tests.ui._meeting_window import HEADSET as HEADSET_SPEAKERS
from tests.ui._meeting_window import (
    LOCAL,
    assign_table,
    build_meeting_window,
    choose,
    end_and_wait,
    start_meeting,
)

MT_BACK = "mt-zh-hans-de"
CONVERSATION = WorkspaceId.CONVERSATION


def in_use(mode: WorkspaceId) -> str:
    return strings.PACK_IN_USE.format(mode=label(mode))


def refused(page, pack_id: str, operation: str) -> str:
    """Start ``operation`` on ``pack_id``; it must be refused: the row's message."""
    source = None if operation == "remove" else DownloadSource(page.transport)
    assert not page.start(pack_id, operation, source, datetime.now(UTC))
    return page.rows[pack_id].message_label.text()


def install_pair(window):
    page = open_page(window)
    for pack_id in (STT, MT, MT_BACK):
        download(page, pack_id)
    return page


def no_pair_notice(window):
    return window.notices.get(catalog.NO_PAIR_READY_KEY)


def test_ac31_no_pair_notice_opens_the_packs_and_resolves_when_a_pair_is_ready(window) -> None:
    notice = no_pair_notice(window)
    assert notice is not None and notice.title == strings.NO_PAIR_READY_TITLE
    assert notice.detail == strings.NO_PAIR_READY_DETAIL
    assert notice.workspace is CONVERSATION
    assert [action.label for action in notice.actions] == [strings.PACKS_OPEN]
    window.refresh_readiness()  # a refresh is not a repeat
    assert no_pair_notice(window).repeats == notice.repeats
    assert window.statusBar().currentMessage() == strings.NO_PAIR_READY  # unchanged CAP-0169

    notice.actions[0].callback()
    assert window.current_workspace() is WorkspaceId.LANGUAGE_PACKS
    install_pair(window)
    # AC-18: the last required pack makes the pair ready without a restart.
    assert wait_until(lambda: no_pair_notice(window) is None)
    assert window.current_pair() is not None and window.start_button.isEnabled()


def test_ac34_the_settings_link_opens_language_packs(window) -> None:
    window.show_workspace(WorkspaceId.SETTINGS)
    link = window.settings.packs_link
    assert link.text() == link.accessibleName() == strings.PACKS_OPEN
    link.click()
    assert window.current_workspace() is WorkspaceId.LANGUAGE_PACKS


def test_ac16_ac19_a_text_only_conversation_protects_its_packs_until_stop(
    window, monkeypatch
) -> None:
    page = install_pair(window)
    # AC-19: no voices — every voice switch is disabled and shows the voice as missing; Meeting is not ready.
    assert wait_until(lambda: window.start_button.isEnabled())
    voice_rows = window.conversation.voice_rows
    for language in voice_rows.languages():
        assert not voice_rows.switch(language).isEnabled()
        assert voice_rows.state_label(language).text() == strings.VOICE_STATE_MISSING
    meeting = window.meeting.availability()
    assert not meeting.available
    assert "Mandarin" in window.meeting.missing_text(meeting.missing)

    window.start_button.click()
    assert wait_until(lambda: window.capture.running)
    usage = window.usage_tracker.current
    assert usage.mode is CONVERSATION and usage.session.mode.output is OutputKind.TEXT
    monkeypatch.setattr(packs_module, "confirm_remove", lambda _parent, _text: True)
    page.rows[MT].remove_button.click()
    assert page.rows[MT].message_label.text() == in_use(CONVERSATION)
    assert refused(page, STT, "update") == in_use(CONVERSATION)
    assert state(page, MT) == strings.PACK_STATE_VALIDATED
    download(page, VOICE_DE)  # an unused pack can be installed meanwhile

    window.stop_listening()
    assert window.session_owner.state is SessionState.IDLE
    assert window.usage_tracker.current is None
    page.rows[MT].remove_button.click()  # allowed after Stop
    assert wait_until(lambda: state(page, MT) == strings.PACK_STATE_DOWNLOADABLE)
    # AC-15: dependent usages are not ready; the cached translator is dropped (spec §3.4).
    assert wait_until(lambda: not window.start_button.isEnabled())  # Automatic needs both edges
    assert window.state_label.text() == "Not available"
    unavailable = strings.MODE_UNAVAILABLE.split("{")[0]
    assert window.statusBar().currentMessage().startswith(unavailable)  # with the reason
    assert window.pipeline.translator is None


def test_ac17_a_failed_pack_recovers_with_download_again(window) -> None:
    page = install_pair(window)
    pack = page.packs.get(MT)
    (page.root / pack.root / pack.files[0].path).unlink()
    page.refresh()
    assert wait_until(lambda: state(page, MT) == strings.PACK_STATE_FAILED)
    assert page.rows[MT].primary_button.text() == strings.PACK_REDOWNLOAD
    window.refresh_readiness()
    assert not window.start_button.isEnabled()  # the mode needing it is not ready
    download(page, MT)
    assert wait_until(lambda: window.start_button.isEnabled())


def test_ac17_the_first_page_snapshot_makes_a_failed_voice_not_ready(window) -> None:
    """A pack installed before this launch: the launch probe (app.py) has no pack files,
    so a missing ``.onnx.json`` is seen only once the page's first snapshot arrives."""
    page, pack = window.language_packs, window.language_packs.packs.get(VOICE_DE)
    source = DownloadSource(page.transport)
    page.installer.install(pack, source, datetime.now(UTC), lambda *_: None, CancelToken())
    launch = ReadinessProbe(page.root, page.manifest_path)  # as ``build_pipeline`` at launch
    window.pipeline.catalog = CapabilityCatalog.from_config(window.config, page.registry, launch)
    german = LanguageId("de")
    assert window.pipeline.catalog.voice(german).status.is_ready
    config = next(f for f in pack.files if f.path.endswith(".onnx.json"))
    (page.root / pack.root / config.path).unlink()
    launch.invalidate()
    assert window.pipeline.catalog.voice(german).status.is_ready  # the launch probe misses it

    open_page(window)  # no manual refresh_readiness()
    assert wait_until(lambda: state(page, VOICE_DE) == strings.PACK_STATE_FAILED)
    assert not window.pipeline.catalog.voice(german).status.is_ready
    assert not window.conversation.session_controller.catalog.voice(german).status.is_ready


def test_ac20_warm_up_shows_the_stage_text_without_percentage_and_retry(
    window,
    spies,  # noqa: F811
) -> None:
    install_pair(window)
    window.show_workspace(CONVERSATION)
    spies.release_warm_up.clear()
    spies.failing_warm_up_calls = {1}
    window.start_button.click()
    texts = (
        window.state_label.text(),
        window.statusBar().currentMessage(),
        window.session_strip.state_label.text(),
    )
    assert texts[0] == "Loading models …"
    assert all("%" not in text for text in texts) and any(texts[1:])
    spies.release_warm_up.set()
    key = catalog.model_failed_key(CONVERSATION)
    assert wait_until(lambda: window.notices.get(key) is not None)
    notice = window.notices.get(key)
    assert [action.label for action in notice.actions] == [strings.NOTICE_RETRY]
    notice.actions[0].callback()
    assert wait_until(lambda: window.capture.running)
    window.stop_listening()


def test_ac16_a_meeting_with_local_speech_protects_its_voice(
    tmp_path,
    monkeypatch,
    spies,  # noqa: F811
) -> None:
    window = build_meeting_window(tmp_path, monkeypatch)
    page, meeting = window.language_packs, window.meeting
    try:
        assign_table(window)
        choose(window, LOCAL, HEADSET_SPEAKERS)
        meeting.speak_local_checkbox.click()
        start_meeting(window)
        usage = window.usage_tracker.current
        assert usage.mode is WorkspaceId.MEETING and usage.local_speech
        assert refused(page, VOICE_DE, "remove") == in_use(WorkspaceId.MEETING)
        assert refused(page, MT, "update") == in_use(WorkspaceId.MEETING)
        meeting.speak_local_checkbox.click()  # off during the meeting
        assert not window.usage_tracker.current.local_speech
        end_and_wait(window)
        owner, tracker = window.session_owner, window.usage_tracker
        assert packs_in_use(owner, tracker, page.packs) == frozenset()  # allowed after End
    finally:
        end_and_wait(window)
        window.close()


def test_ac16_a_call_bridge_session_protects_its_packs(
    tmp_path,
    monkeypatch,
    spies,  # noqa: F811
) -> None:
    window = build_call_bridge_window(tmp_path, monkeypatch)
    page = window.language_packs
    try:
        assign(window)
        window.call_bridge_panel.start_button.click()
        assert wait_until(lambda: window.call_bridge_controller is not None)
        assert window.usage_tracker.current.mode is WorkspaceId.CALL_BRIDGE
        assert refused(page, MT_BACK, "remove") == in_use(WorkspaceId.CALL_BRIDGE)
        assert refused(page, STT, "update") == in_use(WorkspaceId.CALL_BRIDGE)
        window.stop_call_bridge()
        assert window.usage_tracker.current is None
    finally:
        window.stop_call_bridge()
        window.close()


def test_a_status_failure_during_a_job_keeps_cancel_for_the_running_row(
    window, shaped, monkeypatch
) -> None:
    page = open_page(window)
    shaped[3].clear()  # the transfer waits
    download(page, MT, wait=False)
    assert wait_until(lambda: page.rows[MT].cancel_button.isVisible())

    def broken(*_args):
        raise OSError("disk gone")

    monkeypatch.setattr(packs_module, "readiness_pack_files", broken)
    page.refresh()
    assert wait_until(lambda: state(page, MT) == strings.PACK_STATE_UNKNOWN)
    assert page.rows[MT].cancel_button.isVisible()
    assert not page.rows[STT].cancel_button.isVisible()
    page.rows[MT].cancel_button.click()
    shaped[3].set()
    assert wait_until(lambda: page.runner.current is None)
