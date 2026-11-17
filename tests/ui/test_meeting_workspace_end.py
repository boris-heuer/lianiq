"""End of the meeting: the save dialog and the transcript file (CAP-0177 WI-05).

Offscreen UI tests over the real ``MeetingController`` on synthetic adapters
(``_meeting_window.py``). The dialog appears after ``STOPPED`` reached the page, i.e. after the
drain; ``QFileDialog.getSaveFileName`` is replaced as in the Diagnostics export tests. The
Integration half of AC-16 (transcript v2 text and the atomic writer) is in
``tests/meeting/test_transcript.py``.
"""

from __future__ import annotations

import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from lianiq.ui.notices import Severity
from lianiq.ui.shell.session_owner import SessionState
from tests._spy_window import spies  # noqa: F401
from tests.meeting.support import say
from tests.ui._meeting_window import (
    MEETING,
    TABLE,
    USER,
    assign_table,
    build_meeting_window,
    meeting_window,  # noqa: F401
    start_meeting,
)
from tests.ui.test_main_window_session import click, wait_until


@pytest.fixture
def chosen(monkeypatch):
    """``chosen.path`` is what the file dialog returns ("" = cancelled); records each call."""
    from PySide6.QtWidgets import QFileDialog

    class Chosen:
        def __init__(self) -> None:
            self.path = ""
            self.calls: list[tuple] = []

    chosen = Chosen()

    def get_save_file_name(*args):
        chosen.calls.append(args)
        return chosen.path, "Text (*.txt)"

    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(get_save_file_name))
    return chosen


def ended_with_contributions(window, *contributions):
    """Run a meeting with ``(role, tag)`` contributions, End it, wait for the drain."""
    assign_table(window)
    start_meeting(window)
    controller = window.meeting.controller
    for role, tag in contributions:
        say(controller, role, tag)
    click(window.meeting.end_button)
    assert wait_until(lambda: window.session_owner.state is SessionState.IDLE)
    return controller


def dialog_of(window):
    dialog = getattr(window.meeting, "save_dialog", None)
    return dialog if dialog is not None and dialog.isVisible() else None


def button(dialog, text: str):
    return next(b for b in dialog.buttons() if b.text() == text)


# AC-16 -------------------------------------------------------------------------------------


def test_ac16_save_writes_the_transcript_v2_at_the_chosen_path(window, chosen, tmp_path) -> None:
    controller = ended_with_contributions(window, (TABLE, 10), (USER, 20))
    dialog = dialog_of(window)
    assert dialog is not None
    assert dialog.text() == (
        "Save a text transcript in both languages on this computer? Audio is never saved."
    )
    assert [b.text() for b in dialog.buttons()] == ["Save…", "Don't save"]
    chosen.path = str(tmp_path / "meeting.txt")
    click(button(dialog, "Save…"))
    assert wait_until(lambda: (tmp_path / "meeting.txt").exists())
    _parent, _title, default, _filter = chosen.calls[0]
    assert default.endswith(f"lianiq-meeting-{time.strftime('%Y-%m-%d')}.txt")
    text = (tmp_path / "meeting.txt").read_text(encoding="utf-8")
    assert "你好，欢迎" in text and "Hallo, willkommen" in text  # both languages per turn
    assert "Guten Tag" in text and "好的" in text
    assert text.index("你好，欢迎") < text.index("Guten Tag")  # ordered like the view
    assert len(controller.results) == 2
    assert dialog_of(window) is None and window.notices.live(MEETING) == ()


@pytest.mark.parametrize("how", ["dont_save", "close"])
def test_ac16_dont_save_or_closing_the_dialog_writes_nothing(window, chosen, tmp_path, how):
    ended_with_contributions(window, (TABLE, 10))
    dialog = dialog_of(window)
    assert dialog is not None
    if how == "dont_save":
        click(button(dialog, "Don't save"))
    else:
        dialog.close()
    assert wait_until(lambda: dialog_of(window) is None)
    assert chosen.calls == [] and list(tmp_path.glob("*.txt")) == []


def test_ac16_a_write_error_shows_a_notice_naming_the_reason(window, chosen, tmp_path) -> None:
    ended_with_contributions(window, (TABLE, 10))
    chosen.path = str(tmp_path / "missing-folder" / "meeting.txt")
    click(button(dialog_of(window), "Save…"))
    assert wait_until(lambda: window.notices.get("meeting.save-failed") is not None)
    notice = window.notices.get("meeting.save-failed")
    assert notice.title.startswith("The transcript could not be saved: ")
    assert "No such file or directory" in notice.title
    assert str(tmp_path) not in notice.title  # the reason is redacted
    assert notice.severity is Severity.WARNING
    assert list(tmp_path.rglob("*.txt")) == []
    chosen.path = str(tmp_path / "meeting.txt")  # the dialog can be used again
    notice.actions[0].callback()
    assert dialog_of(window) is not None
    click(button(dialog_of(window), "Save…"))
    assert wait_until(lambda: (tmp_path / "meeting.txt").exists())
    assert window.notices.get("meeting.save-failed") is None


@pytest.mark.parametrize("how", ["dont_save", "close"])
def test_ac16_declining_after_a_write_error_clears_its_notice(window, chosen, tmp_path, how):
    ended_with_contributions(window, (TABLE, 10))
    chosen.path = str(tmp_path / "missing-folder" / "meeting.txt")
    click(button(dialog_of(window), "Save…"))
    assert wait_until(lambda: window.notices.get("meeting.save-failed") is not None)
    window.notices.get("meeting.save-failed").actions[0].callback()  # Retry
    dialog = dialog_of(window)
    if how == "dont_save":
        click(button(dialog, "Don't save"))
    else:
        dialog.close()
    assert wait_until(lambda: dialog_of(window) is None)
    assert window.notices.get("meeting.save-failed") is None  # no dead Retry is left
    assert list(tmp_path.rglob("*.txt")) == []


def test_ac16_cancelling_the_file_dialog_writes_nothing_and_asks_again(window, chosen, tmp_path):
    ended_with_contributions(window, (TABLE, 10))
    click(button(dialog_of(window), "Save…"))
    assert len(chosen.calls) == 1 and list(tmp_path.rglob("*.txt")) == []
    assert wait_until(lambda: dialog_of(window) is not None)


# AC-27 -------------------------------------------------------------------------------------


@pytest.mark.parametrize("contributions", [(), ((TABLE, 30), (USER, 40))])
def test_ac27_without_a_translated_contribution_no_dialog_appears(
    window, chosen, tmp_path, contributions
) -> None:
    controller = ended_with_contributions(window, *contributions)
    assert controller.results == ()
    for _ in range(10):
        assert dialog_of(window) is None
        wait_until(lambda: False, 20)
    assert chosen.calls == [] and list(tmp_path.rglob("*.txt")) == []


# Closing the window and the owner ----------------------------------------------------------


def test_closing_the_window_ends_the_meeting_without_a_dialog(
    tmp_path,
    spies,  # noqa: F811
    monkeypatch,
    chosen,
) -> None:
    window = build_meeting_window(tmp_path, monkeypatch)
    assign_table(window)
    start_meeting(window)
    say(window.meeting.controller, TABLE, 10)
    assert wait_until(lambda: len(window.meeting.controller.results) == 1)
    started = time.perf_counter()
    window.close()
    assert time.perf_counter() - started < 0.5  # never blocks
    assert wait_until(lambda: window.session_owner.state is SessionState.IDLE)
    assert not window.meeting.active()
    wait_until(lambda: False, 100)
    assert dialog_of(window) is None and chosen.calls == []


def test_a_stop_without_a_controller_ends_the_session_the_owner_records(window) -> None:
    """``stop_meeting`` with no controller: idle when the owner records the meeting."""
    owner, meeting = window.session_owner, window.meeting
    meeting.stop_meeting()  # idle: nothing to end, nothing changes
    assert owner.state is SessionState.IDLE
    meeting._generation = owner.request_start(MEETING)
    owner.mark_running(meeting._generation)
    assert owner.active is MEETING and meeting.controller is None
    meeting.stop_meeting()
    assert owner.state is SessionState.IDLE and owner.active is None
