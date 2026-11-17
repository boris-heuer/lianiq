"""Meeting notices, device loss and the end-of-meeting dialog (CAP-0177 spec §2.2.2, §2.3).

``MeetingWorkspace`` base (file-size split), plus the Qt-free notice builders of the
CAP-0168 notice model (``lianiq.shell.notice-model.v1``):

| Case | Key | Severity | Action |
|---|---|---|---|
| a meeting endpoint lost (``ENDPOINT_LOST``) | ``meeting.<role>-lost`` | blocking | none (End) |
| the transcript could not be written | ``meeting.save-failed`` | warning | Retry |

Device loss: the shell's 2 s identity monitor (``DeviceWatch.monitor_tick``) calls
``check_endpoints`` while a meeting runs; every assigned endpoint whose identity left is
reported to the controller once (``endpoint_lost``), which stops that input or skips that
output and never opens another device. The notice names the device and its role and stays
until the next start resolves it.

End of the meeting: after ``STOPPED`` reached the GUI thread the page offers the dialog *Save
text transcript?* only if a contribution was translated and the window is still shown;
closing the window ends the meeting without the dialog and writes nothing (the spec is
silent on closing; the close must never block). **Save…** asks for a path
(``QFileDialog``, as the Diagnostics export) and writes the transcript v2 through
``write_meeting_transcript``; cancelling that file dialog asks again; **Don't save** or
closing the dialog writes nothing and forgets the results. A write error shows a notice
naming the (redacted) reason; its **Retry** opens the dialog again.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QMessageBox

from lianiq.audio.device_selection import display_labels
from lianiq.meeting.contracts import CAPTURE_ROLES, MeetingRole
from lianiq.meeting.transcript import meeting_transcript_text, write_meeting_transcript
from lianiq.ui import notice_catalog as catalog
from lianiq.ui import strings
from lianiq.ui.notice_catalog_base import _notice, retry
from lianiq.ui.notices import Notice, Severity
from lianiq.ui.shell.workspaces import WorkspaceId

MEETING = WorkspaceId.MEETING
SAVE_FAILED = "meeting.save-failed"
ROLE_NAMES = {
    MeetingRole.TABLE_CAPTURE: strings.MEETING_TABLE_MIC,
    MeetingRole.TABLE_RENDER: strings.MEETING_TABLE_SPEAKER,
    MeetingRole.USER_CAPTURE: strings.MEETING_USER_MIC,
}


def endpoint_lost_key(role: MeetingRole) -> str:
    return f"meeting.{role.value}-lost"


def endpoint_lost(role: MeetingRole, name: str, role_name: str) -> Notice:
    title = strings.DEVICE_MIC_LOST if role in CAPTURE_ROLES else strings.DEVICE_SPEAKER_LOST
    return _notice(
        endpoint_lost_key(role),
        Severity.BLOCKING,
        title.format(name=name),
        strings.DETAIL_DEVICE,
        catalog.source(MEETING, role_name),
        strings.CONTINUES_SESSION.format(mode=strings.NAV_MEETING),
        MEETING,
    )


def save_failed(reason: str, on_retry) -> Notice:
    """``reason`` must already be redacted (no path, no user name)."""
    return _notice(
        SAVE_FAILED,
        Severity.WARNING,
        strings.MEETING_SAVE_FAILED.format(reason=reason),
        strings.DETAIL_EXPORT,
        catalog.source(MEETING),
        strings.CONTINUES_NOTHING,
        MEETING,
        (retry(on_retry),),
    )


def keys_resolved_by_meeting_start() -> list[str]:
    return [endpoint_lost_key(role) for role in MeetingRole]


def default_transcript_name(today: date | None = None) -> str:
    return f"lianiq-meeting-{(today or date.today()).isoformat()}.txt"


class MeetingEnd:
    """``MeetingWorkspace`` base: endpoint loss and the end-of-meeting save dialog."""

    save_dialog: QMessageBox | None = None
    _unsaved: tuple | None = None  # (pair, results) offered for saving

    # Device loss -----------------------------------------------------------------------

    def check_endpoints(self) -> None:
        """Report each assigned endpoint whose identity left (``DeviceWatch`` 2 s tick)."""
        controller = self.controller
        if controller is None or self.stopping:
            return
        state = self.host.device_setup.state
        for role, endpoint in _assigned(controller.endpoints).items():
            if role not in controller.lost_roles and not state.present(endpoint.endpoint_id):
                controller.endpoint_lost(role)

    def show_endpoint_lost(self, role: MeetingRole) -> None:
        controller = self.controller
        endpoint = None if controller is None else _assigned(controller.endpoints).get(role)
        if endpoint is None:
            return
        labels = display_labels(self.inventory().endpoints)
        name = labels.get(endpoint.endpoint_id, endpoint.display_name)
        local_name, _table = self.language_names()
        role_name = ROLE_NAMES.get(role) or strings.MEETING_LOCAL_OUTPUT.format(language=local_name)
        self.host.post_notice(endpoint_lost(role, name, role_name))

    # End of the meeting ----------------------------------------------------------------

    def meeting_ended(self, controller) -> None:
        """``STOPPED`` reached the page: offer to save what was translated, if anything."""
        results = controller.results
        if not results or not self.host.isVisible():
            return  # nothing translated, or the window closed: nothing is written
        self._unsaved = (controller.session.pair, results)
        self.offer_save()

    def offer_save(self) -> None:
        if self._unsaved is None:
            return
        dialog = QMessageBox(self.host)
        dialog.setIcon(QMessageBox.Icon.Question)
        dialog.setWindowTitle(strings.NAV_MEETING)
        dialog.setText(strings.MEETING_SAVE_PROMPT)
        save = dialog.addButton(strings.MEETING_SAVE, QMessageBox.ButtonRole.AcceptRole)
        dont = dialog.addButton(strings.MEETING_DONT_SAVE, QMessageBox.ButtonRole.RejectRole)
        for button in (save, dont):
            button.setAccessibleName(button.text())
        dialog.setDefaultButton(save)
        dialog.setEscapeButton(dont)  # closing the dialog = Don't save
        dialog.finished.connect(lambda _result: self._answered(dialog.clickedButton() is save))
        self.save_dialog = dialog
        dialog.open()

    def _answered(self, save: bool) -> None:
        self.save_dialog = None
        if not save:
            self._unsaved = None  # nothing is written
            self.host.notices.resolve(SAVE_FAILED)  # its Retry has nothing left to save
            return
        default = str(Path.home() / default_transcript_name())
        path, _filter = QFileDialog.getSaveFileName(
            self.host, strings.TRANSCRIPT_EXPORT, default, strings.DIAG_EXPORT_FILTER
        )
        if not path:
            self.offer_save()  # nothing written; the PO can save or decline again
            return
        pair, results = self._unsaved
        try:
            write_meeting_transcript(Path(path), meeting_transcript_text(pair, results))
        except OSError as exc:
            reason = self.host.diagnostics.redact(exc.strerror or type(exc).__name__)
            self.host.post_notice(save_failed(reason, self.offer_save))
            return
        self._unsaved = None
        self.host.notices.resolve(SAVE_FAILED)


def _assigned(endpoints) -> dict:
    assigned = {
        MeetingRole.TABLE_CAPTURE: endpoints.table_capture,
        MeetingRole.TABLE_RENDER: endpoints.table_render,
        MeetingRole.USER_CAPTURE: endpoints.user_capture,
    }
    local = endpoints.local_render
    if local is not None and local.endpoint_id != endpoints.table_render.endpoint_id:
        assigned[MeetingRole.LOCAL_RENDER] = local  # one device in two roles: one notice
    return assigned
