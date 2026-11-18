"""E-10: Settings › Diagnostics › Export… to a file and onto a write-protected file (contract §5).

The row uses the app E-03 left open (so the log holds that session), or starts one. It
writes ``%TEMP%\\lianiq-e2e\\ro\\diagnostics-E10.txt`` (a writable folder) and denies the
test user writes to that file with ``icacls`` (proved by a refused append). **Export…** opens
the save dialog; the row types the path into the dialog's file-name ``Edit``
(``AutomationId`` 1001) and presses Enter: ``%TEMP%\\lianiq-e2e\\diagnostics-E10.txt`` is
written and contains none of the forbidden patterns (``forbidden_classes``; only the class
names are stored). The second export targets the protected file: the dialog asks whether to
replace it, the row answers **Yes** (``CommandButton_6``), and Lianiq shows its own
"Export failed" notice without "Saved", the file keeps its content and the event list stays.
A write-protected *folder* cannot be used: the save dialog itself refuses it, so the path
never reaches Lianiq (PO decision after native run 44267851808). Only the notice elements
are read for the failure: the notice history logs every posted notice title, so the first
export's "saved" line is always in it. A dialog still open is cancelled before the masked
screenshot and the close. T-03 resets the ACLs and deletes the folder.
"""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

from native_e2e import audio, uia_app
from native_e2e.context import RunContext
from native_e2e.data.make_test_phrase import PHRASE
from native_e2e.evidence.model import Check, Row, Status
from native_e2e.evidence.redaction import _USER
from native_e2e.rows import ui
from native_e2e.rows.common import check, make_row
from native_e2e.rows.ui import transcript_needles
from native_e2e.uia import Node

EXPORT_NAME = "diagnostics-E10.txt"
# AutomationId of the file-name Edit: 1001 in the Windows save dialog (inside the
# "FileNameControlHost" combo box); 1148, the former id, is kept for an Edit that carries it.
# A toolbar of the save dialog also carries 1001, so only an Edit counts.
FILE_NAME_FIELDS = ("1001", "1148")
# AutomationId of "Yes" in the save dialog's "already exists, replace?" prompt: the task
# dialog's CommandButton_6 (IDYES); 6 is the classic message box's id.
REPLACE_YES = ("CommandButton_6", "6")
# Write data, append, write (extended) attributes; plain (W) also denies SYNCHRONIZE, which
# blocks reading the file back.
WRITE_RIGHTS = "(WD,AD,WEA,WA)"
PROTECTED_CONTENT = "lianiq-e2e write-protected\n"
CANCEL_BUTTON = "2"  # AutomationId of the dialog's Cancel button (IDCANCEL)
SCREEN = "screens/e10-export-failed.png"
_DRIVE_PATH = re.compile(r"[A-Za-z]:\\")
_ENDPOINT_ID = re.compile(r"\{0\.0\.[01]\.")


def forbidden_classes(
    text: str,
    *,
    transcripts: Iterable[str],
    phrase: str,
    username: str,
    profile: str,
    endpoint_ids: Iterable[str],
) -> list[str]:
    """The contract §5 E-10 pattern classes found in ``text`` (never the matched text)."""
    folded = text.casefold()
    found: set[str] = set()
    if any(needle.casefold() in folded for needle in transcript_needles(transcripts)):
        found.add("transcript")
    if phrase and phrase.casefold() in folded:
        found.add("test-phrase")
    if username and re.search(_USER.format(re.escape(username)), text, re.IGNORECASE):
        found.add("username")
    if profile and profile.casefold() in folded:
        found.add("profile-path")
    if _DRIVE_PATH.search(text):
        found.add("drive-path")
    if _ENDPOINT_ID.search(text):
        found.add("endpoint-id")
    if any(item and item.casefold() in folded for item in endpoint_ids):
        found.add("cable-endpoint-id")
    return sorted(found)


def deny_write(path: Path) -> bool:
    """Write ``path``, deny the test user writes to it (``icacls``); true iff an append fails."""
    user = os.environ.get("USERNAME", "")
    if not user:
        return False
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(PROTECTED_CONTENT, encoding="utf-8")
        subprocess.run(
            ["icacls", str(path), "/deny", f"{user}:{WRITE_RIGHTS}"],
            capture_output=True,
            check=False,
        )
    except OSError:
        return False
    try:
        with path.open("a", encoding="utf-8") as probe:
            probe.write("x")
    except PermissionError:
        return True
    return False


def _unchanged(path: Path) -> bool:
    try:
        return path.read_text(encoding="utf-8") == PROTECTED_CONTENT
    except OSError:
        return False


def _field(nodes: list[Node] | None) -> Node | None:
    return next(
        (
            node
            for node in nodes or ()
            if node.automation_id in FILE_NAME_FIELDS and node.control_type == "Edit"
        ),
        None,
    )


def _replace_yes(nodes: list[Node] | None) -> Node | None:
    return next(
        (
            node
            for node in nodes or ()
            if node.automation_id in REPLACE_YES and node.control_type == "Button"
        ),
        None,
    )


def export(app: Any, s: Any, path: Path, *, replace: bool = False) -> tuple[bool, bool]:
    """**Export…**, type ``path`` into the file-name field, Enter; with ``replace`` answer the
    "replace?" prompt with Yes. Returns (the dialog closed, the prompt was answered)."""
    button = ui.find(app.nodes(), s.DIAG_EXPORT, "Button")
    if button is None:
        return False, False
    app.press(button)
    answered = False
    try:
        field = ui.wait(lambda: _field(app.window_nodes(s.DIAG_EXPORT_TITLE)))
        app.type_into(field, str(path))
        if replace:
            app.press(ui.wait(lambda: _replace_yes(app.window_nodes(s.DIAG_EXPORT_TITLE))))
            answered = True
        ui.wait(lambda: app.window_nodes(s.DIAG_EXPORT_TITLE) is None)
    except TimeoutError:
        return False, answered
    return True, answered


def _history(nodes: list[Node], s: Any) -> list[str]:
    # The group box carries the same name and an empty value; the text is in its Edit field.
    field = next(
        (n for n in nodes if n.visible and n.name == s.DIAG_HISTORY and n.control_type == "Edit"),
        None,
    )
    return [line for line in (field.value or "").splitlines() if line] if field else []


def _dismiss(app: Any, s: Any) -> None:
    """Cancel the export dialog if it is still open (else nothing)."""
    nodes = app.window_nodes(s.DIAG_EXPORT_TITLE)
    if nodes is None:
        return
    cancel = [n for n in nodes if n.automation_id == CANCEL_BUTTON and n.control_type == "Button"]
    if cancel:
        app.press(cancel[0])
    else:
        app.keys("{ESC}")
    try:
        ui.wait(lambda: app.window_nodes(s.DIAG_EXPORT_TITLE) is None)
    except TimeoutError:
        pass  # the close below still ends the app


def _notice_texts(nodes: list[Node], s: Any) -> Iterator[str]:
    """The texts of the shown notice elements: everything but the notice history."""
    for node in nodes:
        if node.visible and s.DIAG_HISTORY not in (node.name, *node.parents):
            yield from node.texts()


def _failure(nodes: list[Node], s: Any, prefix: str) -> str | None:
    return next((text for text in _notice_texts(nodes, s) if prefix in text), None)


def _checks(ctx: RunContext, app: Any) -> tuple[list[Check], list]:
    s = ui.strings()
    target, protected = ctx.temp / EXPORT_NAME, ctx.temp / "ro" / EXPORT_NAME
    checks = [check("ro-file-denies-write", deny_write(protected))]
    if checks[-1].result is not Status.PASS:
        return checks, []
    if not ui.select(app, s.NAV_SETTINGS, s.NAV_REGION):
        return [*checks, check("file-written", False, "settings-not-shown")], []
    written, _ = export(app, s, target)
    try:
        ui.wait(target.is_file)
    except TimeoutError:
        pass  # recorded below
    checks.append(check("file-written", written and target.is_file()))
    if not target.is_file():
        return checks, []
    found = forbidden_classes(
        target.read_text(encoding="utf-8", errors="replace"),
        transcripts=ctx.state.get("transcripts", []),
        phrase=PHRASE,
        username=os.environ.get("USERNAME", ""),
        profile=os.environ.get("USERPROFILE", ""),
        endpoint_ids=audio.cable_endpoint_ids(),
    )
    checks.append(check("no-forbidden-pattern", not found, ", ".join(found) or None))
    before = _history(app.nodes(), s)
    closed, answered = export(app, s, protected, replace=True)
    prefix = s.EXPORT_FAILED.split("{reason}")[0]
    try:
        notice = ui.wait_nodes(app, lambda nodes: _failure(nodes, s, prefix))
    except TimeoutError:
        notice = None
    nodes = app.nodes()
    saved = s.DIAG_EXPORT_SAVED.split("{name}")[0]
    shown = notice is not None and _unchanged(protected)
    without = notice is not None and "saved" not in notice.casefold()
    without = without and not any(saved in text for text in _notice_texts(nodes, s))
    after = _history(nodes, s)
    checks += [
        check("overwrite-confirmed", answered),
        check("failure-notice-shown", shown, f"dialog-closed: {str(closed).lower()}"),
        check("notice-without-saved", without),
        check("event-list-kept", bool(before) and all(line in after for line in before)),
    ]
    _dismiss(app, s)
    shot, artifact = ui.screenshot(ctx, app, SCREEN, "screenshot-masked")
    return [*checks, shot], [artifact]


def run(ctx: RunContext) -> Row:
    app = ctx.state.pop("app", None) or uia_app.launch(ctx)
    try:
        checks, artifacts = _checks(ctx, app)
    finally:
        try:
            _dismiss(app, ui.strings())
        finally:  # the app is out of ctx.state, so it must close even if the dismiss raises
            app.close()
    return make_row("E-10", checks, artifacts, reason="diagnostics-export")
