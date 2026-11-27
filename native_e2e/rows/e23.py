"""E-23: session rule, limit and privacy of Text translation (CAP-0172 e2e plan E-05, E-06, E-08).

Image models. Settings › Audio devices: "CABLE Output" as Microphone, "CABLE Input" as Speakers
(``name_matches`` only). Conversation **Start** (F8); Text translation: D-03 is translated
while Conversation runs; **Play translation** is refused with "Stop the Conversation session
first" and nothing plays; F9 stops Conversation and Play then runs; F9 pressed in Settings
stops it and both texts are unchanged on return. Limit: D-06 (50,001 code points, pasted)
shows ``TEXT_TOO_LONG`` with the count and disables **Translate**; one Backspace (50,000)
enables it. Privacy: the sentinel D-05 is translated and played (F9 ends it), Settings ›
Diagnostics **Export…** writes ``%TEMP%\\lianiq-e2e\\diagnostics-E23.txt``; after a restart
*Source text* is empty and no log, the export or a ``config\\settings*.json`` holds "QX7"
(counts only). Both panes are masked in every screenshot; the texts go to ``ctx.secrets``.
The row resets the settings to the S-03 baseline at its end.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from native_e2e import uia_app
from native_e2e.context import RunContext
from native_e2e.evidence.model import Check, Method, Row
from native_e2e.rows import e03, e10, e13, text_flow, ui
from native_e2e.rows.common import check, make_row
from native_e2e.rows.text_flow import GERMAN, MANDARIN, button

EXPORT_NAME = "diagnostics-E23.txt"
SCREENS = ("screens/e23-busy.png", "screens/e23-too-long.png")
NEEDLE = "QX7"


def _conversation(app: Any, s: Any, checks: list[Check]) -> bool:
    running = s.SESSION_RUNNING.format(mode=s.NAV_CONVERSATION)
    if not e03._cable_microphone(app, s, checks) or not e13._cable_speakers(app, s, checks):
        return False
    if not ui.select(app, s.NAV_CONVERSATION, s.NAV_REGION):
        checks.append(check("conversation-running", False, "not-selected"))
        return False
    app.keys("{F8}")
    probe = lambda: ui.shows(app.nodes(), running)
    return ui.waited(checks, "conversation-running", probe, ui.MODEL_TIMEOUT_S)


def _session_rule(ctx, app: Any, s: Any, checks: list[Check], artifacts: list) -> bool:
    if not _conversation(app, s, checks):
        return False
    if not text_flow.open_page(app, s, checks, "translate-during-conversation"):
        return False
    if not text_flow.direction(app, s, GERMAN, MANDARIN) or not text_flow.type_source(
        app, s, text_flow.D03
    ):
        checks.append(check("translate-during-conversation", False, "not-typed"))
        return False
    text_flow.remember(ctx, text_flow.D03)
    before = text_flow.translated(ctx, app, s, checks, "translate-during-conversation")
    play = button(app.nodes(), s.TEXT_PLAY) if before else None
    if play is None:
        checks.append(check("play-refused-session-busy", False, "play-disabled"))
        return False
    app.press(play)
    busy = s.SESSION_BUSY.format(mode=s.NAV_CONVERSATION)
    probe = lambda: ui.shows(app.nodes(), busy) and not text_flow.running(app.nodes(), s)
    if not ui.waited(checks, "play-refused-session-busy", probe):
        return False
    shot, artifact = text_flow.shot(ctx, app, SCREENS[0], before, "screenshot-busy-masked")
    checks.append(shot)
    artifacts.append(artifact)
    app.keys("{F9}")
    if not ui.waited(checks, "f9-stops-conversation", lambda: text_flow.strip_gone(app.nodes(), s)):
        return False
    play = button(app.nodes(), s.TEXT_PLAY) or button(app.nodes(), s.TEXT_REPLAY)
    if play is not None:
        app.press(play)
    probe = lambda: text_flow.running(app.nodes(), s)
    if not ui.waited(checks, "plays-after-stop", probe, ui.MODEL_TIMEOUT_S):
        return False
    if not ui.select(app, s.NAV_SETTINGS, s.NAV_REGION):
        checks.append(check("f9-from-settings-stops", False, "not-selected"))
        return False
    app.keys("{F9}")
    probe = lambda: text_flow.strip_gone(app.nodes(), s)
    if not ui.waited(checks, "f9-from-settings-stops", probe):
        return False
    if not text_flow.open_page(app, s, checks, "texts-unchanged"):
        return False
    same = text_flow.panes(app.nodes(), s) == before
    checks.append(check("texts-unchanged", same, None if same else "changed"))
    return True


def _limit(ctx, app: Any, s: Any, checks: list[Check], artifacts: list) -> bool:
    text, limit = text_flow.over_limit(), text_flow.limit()
    text_flow.remember(ctx, text)
    if not text_flow.paste_source(app, s, text):
        checks.append(check("too-long-translate-disabled", False, "not-pasted"))
        return False
    message = s.TEXT_TOO_LONG.format(count=len(text), limit=limit)

    def too_long() -> bool:
        nodes = app.nodes()
        translate = ui.find(nodes, s.TEXT_TRANSLATE, "Button")
        return ui.shows(nodes, message) and translate is not None and not translate.enabled

    if not ui.waited(checks, "too-long-translate-disabled", too_long):
        return False
    shot, artifact = text_flow.shot(ctx, app, SCREENS[1], (), "screenshot-too-long-masked")
    checks.append(shot)
    artifacts.append(artifact)
    app.keys("{BACKSPACE}")

    def at_limit() -> bool:
        nodes = app.nodes()
        source = text_flow.panes(nodes, s)[0] or ""
        enabled = button(nodes, s.TEXT_TRANSLATE) is not None
        return len(source) == limit and enabled and not ui.shows(nodes, message)

    return ui.waited(checks, "at-limit-translate-enabled", at_limit)


def _sentinel(ctx, app: Any, s: Any, checks: list[Check]) -> Path | None:
    if not text_flow.type_source(app, s, text_flow.SENTINEL):
        checks.append(check("sentinel-translated", False, "not-typed"))
        return None
    text_flow.remember(ctx, text_flow.SENTINEL)
    if text_flow.translated(ctx, app, s, checks, "sentinel-translated") is None:
        return None
    play = button(app.nodes(), s.TEXT_PLAY) or button(app.nodes(), s.TEXT_REPLAY)
    if play is not None:
        app.press(play)
    probe = lambda: text_flow.running(app.nodes(), s)
    if not ui.waited(checks, "sentinel-played", probe, ui.MODEL_TIMEOUT_S):
        return None
    app.keys("{F9}")
    ui.waited(checks, "sentinel-playback-stopped", lambda: text_flow.idle(app.nodes(), s))
    target = ctx.temp / EXPORT_NAME
    if not ui.select(app, s.NAV_SETTINGS, s.NAV_REGION):
        checks.append(check("diagnostics-exported", False, "not-selected"))
        return None
    written, _ = e10.export(app, s, target)
    try:
        ui.wait(target.is_file)
    except TimeoutError:
        pass  # recorded below
    checks.append(check("diagnostics-exported", written and target.is_file()))
    return target if target.is_file() else None


def needle_files(paths: list[Path], needle: str = NEEDLE) -> tuple[int, int]:
    """(files read, files holding ``needle``): never a line or a path."""
    read = hits = 0
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        read += 1
        hits += needle.casefold() in text.casefold()
    return read, hits


def _restart(ctx: RunContext, export: Path, checks: list[Check]) -> None:
    s = ui.strings()
    app = uia_app.launch(ctx)
    try:
        if text_flow.open_page(app, s, checks, "source-empty-after-restart"):
            probe = lambda: text_flow.panes(app.nodes(), s)[0] == ""
            ui.waited(checks, "source-empty-after-restart", probe)
    finally:
        app.close()
    logs = ctx.repo / "logs"
    files = [p for p in logs.rglob("*") if p.is_file()] if logs.is_dir() else []
    files += [export, *sorted((ctx.repo / "config").glob("settings*.json"))]
    read, hits = needle_files(files)
    checks.append(check("sentinel-in-no-file", read > 0 and hits == 0, f"files={read} hits={hits}"))


def run(ctx: RunContext) -> Row:
    checks: list[Check] = []
    artifacts: list = []
    try:
        app = uia_app.launch(ctx)
        export = None
        try:
            s = ui.strings()
            if _session_rule(ctx, app, s, checks, artifacts) and _limit(
                ctx, app, s, checks, artifacts
            ):
                export = _sentinel(ctx, app, s, checks)
        finally:
            app.close()
        if export is not None:
            _restart(ctx, export, checks)
    finally:
        uia_app.settings_reset(ctx)
    return make_row(
        "E-23", checks, artifacts, reason="text-session-limit-privacy", method=Method.VIRTUAL_DEVICE
    )
