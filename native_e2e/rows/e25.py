"""E-25: Listen & translate in both directions on the E-24 scratch models (CAP-0170 E-02, E-03).

Runs inside the E-24 group (``rows/e24.py``) with its app, after the assistant imported the
recognition pack and ``de>zh-Hans``. Listen & translate: German → Mandarin (Simplified),
*Microphone* "CABLE Output" (``e14._setup``; only ``name_matches`` stored); **Start
listening**; ``listen_de3_16k.wav`` into "CABLE Input"; exactly three translated rows, each
closest to the fixture sentence at its position (speech order); F9; no WASAPI render session
of the app (no output stream). **Swap languages**: **Start listening** disabled, the page
names only the missing "translation Mandarin (Simplified) → German" and offers **Open
Language packs**. Language packs: ``zh-Hans>de`` imported from its image folder
(``packs_import.import_folder``, *Validated*); back on Listen & translate **Start listening**
is enabled without a restart. Mandarin → German, ``listen_zh_de_16k.wav`` (one Mandarin, one
German sentence): every new row has Mandarin as source and German as target (the German
sentence is never shown as a Mandarin target) and one is translated; F9. **Copy transcript**
and **Export transcript** (to ``%TEMP%\\lianiq-e2e\\listen-E25.txt``): the clipboard equals the
file (line ends normalised), transcript v2 with three ``de -> zh-Hans`` turns and one
``zh-Hans -> de`` turn per translated new row. Stored: counts, SHA-256 and one masked
screenshot; every row text goes to ``ctx.secrets``; file and clipboard stay in the VM.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from native_e2e import audio, fixtures, packs_import
from native_e2e.context import RunContext
from native_e2e.evidence.model import Check, Row
from native_e2e.evidence.sums import file_sha256
from native_e2e.rows import e10, e14, ui
from native_e2e.rows import listen_flow as lf
from native_e2e.rows.common import blocked_row, check
from native_e2e.rows.listen_flow import GERMAN, MANDARIN

STATE_KEY = "e24_group"  # the rows of the E-24 group
EXPORT_NAME = "listen-E25.txt"
SCREEN = "screens/e25-listen.png"
ROWS = 3  # sentences of listen_de3_16k.wav


def _german_to_mandarin(ctx, app, s, path: Path, checks: list[Check]) -> bool:
    if not e14._setup(app, s, checks) or not lf.start(app, s, checks, "session-running"):
        return False
    audio.play_into_cable(path)
    enough = lambda new: (
        len(new) >= ROWS and all(lf.translated(t, GERMAN, MANDARIN, s) for t in new)
    )
    try:
        new = lf.settle(app, s, 0, enough)
    except TimeoutError:
        checks.append(check("three-rows-in-order", False, "timeout"))
        return False
    lf.remember(ctx, new, GERMAN, MANDARIN)
    sources = [lf.parts(t, GERMAN, MANDARIN)[0] for t in new]
    ordered = lf.in_order(sources, fixtures.TEXTS["listen_de3_16k.wav"])
    translations = [lf.parts(t, GERMAN, MANDARIN)[1] for t in new]
    checks += [
        check("three-rows-in-order", len(new) == ROWS and ordered, f"rows={len(new)}"),
        check("translations-sha256", True, f"sha256={e14.digest(translations)}"),
    ]
    app.keys("{F9}")
    if not ui.waited(checks, "stopped-with-f9", lambda: lf.idle(app.nodes(), s)):
        return False
    checks.append(e14._no_render(app))
    return True


def _swap_names_missing(app, s, checks: list[Check]) -> bool:
    swap = ui.find(app.nodes(), s.LISTEN_SWAP, "Button")
    if swap is None:
        checks.append(check("swap-start-disabled-names-pack", False, "not-shown"))
        return False
    app.press(swap)
    wanted = (lf.name(MANDARIN), lf.name(GERMAN))
    text = lf.missing(s, MANDARIN, GERMAN)

    def blocked() -> bool:
        nodes = app.nodes()
        start = ui.find(nodes, s.LISTEN_START, "Button")
        packs = ui.find(nodes, s.PACKS_OPEN, "Button") is not None
        disabled = start is not None and not start.enabled
        return lf.combos(nodes, s) == wanted and disabled and ui.shows(nodes, text) and packs

    return ui.waited(checks, "swap-start-disabled-names-pack", blocked)


def _import_backward(app, s, folder: Path, checks: list[Check]) -> bool:
    result = packs_import.import_folder(app, lf.packs()[f"{MANDARIN}>{GERMAN}"], folder)
    checks.append(check("imported-zh-hans-de", result == "validated", result))
    if result != "validated":
        return False
    if not ui.select(app, s.NAV_LISTEN, s.NAV_REGION):
        checks.append(check("start-enabled-without-restart", False, "not-selected"))
        return False

    def enabled() -> bool:
        start = ui.find(app.nodes(), s.LISTEN_START, "Button")
        return start is not None and start.enabled

    return ui.waited(checks, "start-enabled-without-restart", enabled)


def _mandarin_to_german(ctx, app, s, path: Path, checks: list[Check]) -> int | None:
    count = len(lf.rows(app.nodes()))
    if not lf.start(app, s, checks, "session-running-zh-hans-de"):
        return None
    audio.play_into_cable(path)
    try:
        new = lf.settle(app, s, count, lambda new: True)
    except TimeoutError:
        checks.append(check("mandarin-rows-to-german", False, "timeout"))
        return None
    lf.remember(ctx, new, MANDARIN, GERMAN)
    done = [t for t in new if lf.translated(t, MANDARIN, GERMAN, s)]
    checks += [
        check(
            "mandarin-rows-to-german",
            all(lf.direction_ok(t, MANDARIN, GERMAN) for t in new),
            f"rows={len(new)}",
        ),
        check("mandarin-row-translated", bool(done), f"translated={len(done)}"),
    ]
    app.keys("{F9}")
    if not ui.waited(checks, "stopped-zh-hans-de", lambda: lf.idle(app.nodes(), s)):
        return None
    return len(done)


def save_as(app: Any, title: str, path: Path) -> bool:
    """Type ``path`` into the open save dialog ``title`` and press Enter (as E-10)."""
    try:
        field = ui.wait(lambda: e10._field(app.window_nodes(title)))
        app.type_into(field, str(path))
        ui.wait(lambda: app.window_nodes(title) is None)
        ui.wait(path.is_file)
    except TimeoutError:
        return False
    return True


def clipboard_text() -> str | None:
    try:
        import win32clipboard
        import win32con

        win32clipboard.OpenClipboard()
        try:
            return str(win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT))
        finally:
            win32clipboard.CloseClipboard()
    except Exception:  # noqa: BLE001 - no text on the clipboard, or it is held elsewhere
        return None


def _norm(text: str | None) -> str | None:
    return text.replace("\r\n", "\n") if text is not None else None


def _copy_and_export(ctx, app, s, backward: int, checks: list[Check]) -> None:
    from lianiq.languages.session import TRANSCRIPT_V2_HEADER

    copy = ui.find(app.nodes(), s.LISTEN_COPY, "Button")
    if copy is None or not copy.enabled:
        checks.append(check("clipboard-equals-export", False, "copy-not-enabled"))
        return
    app.press(copy)
    try:
        clip = ui.wait(lambda: (t := clipboard_text()) and t.startswith(TRANSCRIPT_V2_HEADER) and t)
    except TimeoutError:
        checks.append(check("clipboard-equals-export", False, "clipboard-empty"))
        return
    path = ctx.temp / EXPORT_NAME
    path.unlink(missing_ok=True)
    export = ui.find(app.nodes(), s.LISTEN_EXPORT, "Button")
    if export is None or not export.enabled:
        checks.append(check("clipboard-equals-export", False, "export-not-enabled"))
        return
    app.press(export)
    if not save_as(app, s.LISTEN_EXPORT, path):
        checks.append(check("clipboard-equals-export", False, "not-written"))
        return
    text = _norm(path.read_text(encoding="utf-8"))
    same = text == _norm(clip)
    checks.append(check("clipboard-equals-export", same, f"sha256={file_sha256(path)}"))
    turns = [re.search(r"\] (\S+) -> (\S+)$", line) for line in (text or "").splitlines()]
    pairs = [m.groups() for m in turns if m]
    forward, back = pairs.count((GERMAN, MANDARIN)), pairs.count((MANDARIN, GERMAN))
    ok = forward == ROWS and back == backward and len(pairs) == forward + back
    checks.append(check("transcript-v2-turns", ok, f"de-zh={forward} zh-de={back}"))


def e25(ctx: RunContext, app: Any, paths: list, folder: Path, artifacts: list) -> list[Check]:
    s, checks = ui.strings(), []
    if not _german_to_mandarin(ctx, app, s, paths[0], checks):
        return checks
    if not _swap_names_missing(app, s, checks) or not _import_backward(app, s, folder, checks):
        return checks
    backward = _mandarin_to_german(ctx, app, s, paths[1], checks)
    if backward is None:
        return checks
    _copy_and_export(ctx, app, s, backward, checks)
    shot, artifact = lf.shot(ctx, app, SCREEN, "screenshot-masked")
    checks.append(shot)
    artifacts.append(artifact)
    return checks


def run(ctx: RunContext) -> Row:
    """E-25 as the E-24 group recorded it (E-24 runs first)."""
    return ctx.state.get(STATE_KEY, {}).get("E-25") or blocked_row("E-25", "group-not-run")
