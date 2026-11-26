"""E-32: keyboard only on Listen & translate and Text translation (automated-po-rows spec §2.2).

The keyboard parts of CAP-0170 E-07 (AC-30) and CAP-0172 E-07 (AC-19, AC-36), read through UI
Automation. On the image models the row starts its own app. Listen & translate: German →
Mandarin, *Microphone* "CABLE Output" (as E-14), the Tab cycle is walked (every stop named);
F8 starts listening ("Listening…" and the strip), F9 stops it (**Start listening (F8)**
enabled again). Nothing is played.

Text translation: the plan's German text D-03 (E-13) is typed into *Source text*; Ctrl+Enter
translates it (the result settles, SHA-256 only). Tab leaves *Source text* and *Translation*
(the focus moves on and the source is unchanged); the Tab cycle is walked. The source is
then made 31 copies long with the keyboard (Ctrl+A, Ctrl+C, End, Enter and Ctrl+V), so the
next translation runs long enough to be seen: **Translate** is focused and Enter starts it;
the focused button is then named **Cancel** (the name follows the label); Escape cancels it:
"Translation cancelled. Your text is unchanged.", the source is unchanged and the focused
button is named **Translate** again.

Fixture and result lines go to ``ctx.secrets``; the row stores no text. The app is closed and
the settings file is reset to the S-03 baseline (the Listen languages and microphone).
"""

from __future__ import annotations

from typing import Any

from native_e2e import uia_app
from native_e2e.context import RunContext
from native_e2e.evidence.model import Check, Method, Row
from native_e2e.rows import e03, e13, e14, keys, ui
from native_e2e.rows.common import check, make_row

COPIES = 30  # pasted copies of D-03: about 3,100 characters, below the 5,000 limit
LONG = e13.FIXTURE + ("\n" + e13.FIXTURE) * COPIES


def _listen(app: Any, s: Any, checks: list[Check]) -> None:
    if not e14._setup(app, s, checks):
        return
    checks.append(keys.walk(app, "listen-tab-stops-named"))
    running = s.SESSION_RUNNING.format(mode=s.NAV_LISTEN)

    def listening() -> bool:
        nodes = app.nodes()
        state = ui.shows(nodes, s.LISTEN_STATE_LISTENING) or ui.shows(
            nodes, s.LISTEN_STATE_PROCESSING
        )
        return state and ui.shows(nodes, running)

    app.keys("{F8}")
    if ui.waited(checks, "f8-starts-listening", listening, ui.MODEL_TIMEOUT_S):
        app.keys("{F9}")
        ui.waited(checks, "f9-stops-listening", lambda: e14._idle(app.nodes(), s, running))


def _source(app: Any, s: Any) -> str | None:
    return e13.panes(app.nodes(), s)[0]


def _leaves(app: Any, s: Any, checks: list[Check], label: str, name: str) -> None:
    if keys.tab_to(app, keys.named(label)) is None:
        checks.append(check(name, False, "not-a-tab-stop"))
        return
    app.keys("{TAB}")
    moved = keys.became(lambda: not keys.focused_is(app, label))
    same = _source(app, s) == e13.FIXTURE
    checks.append(check(name, moved and same, None if moved and same else "focus-kept"))


def _cancel(app: Any, s: Any, checks: list[Check]) -> None:
    if keys.tab_to(app, keys.named(s.TEXT_SOURCE_LABEL)) is None:
        checks.append(check("enter-on-focused-button", False, "source-not-a-tab-stop"))
        return
    app.keys("^a^c{END}" + "{ENTER}^v" * COPIES)
    if not keys.became(lambda: _source(app, s) == LONG):
        checks.append(check("enter-on-focused-button", False, "source-not-grown"))
        return
    if keys.tab_to(app, keys.named(s.TEXT_TRANSLATE, "Button")) is None:
        checks.append(check("enter-on-focused-button", False, "not-a-tab-stop"))
        return
    app.keys("{ENTER}")
    probe = lambda: ui.find(app.nodes(), s.TEXT_CANCEL, "Button")
    if not ui.waited(checks, "enter-on-focused-button", probe):
        return
    checks.append(check("focused-button-named-cancel", keys.focused_is(app, s.TEXT_CANCEL)))
    app.keys("{ESC}")

    def cancelled() -> bool:
        nodes = app.nodes()
        shown = ui.shows(nodes, s.TEXT_CANCELLED)
        return shown and e13.panes(nodes, s)[0] == LONG

    if ui.waited(checks, "escape-cancels-translation", cancelled):
        back = keys.became(lambda: keys.focused_is(app, s.TEXT_TRANSLATE))
        checks.append(check("focused-button-named-translate", back))


def _text(ctx: RunContext, app: Any, s: Any, checks: list[Check]) -> None:
    if not e13._typed(app, s, checks):
        return
    app.keys("^{ENTER}")  # the focus is in Source text after typing
    try:
        texts = e13._settled(app, s)
    except TimeoutError:
        checks.append(check("ctrl-enter-translates", False, "timeout"))
        return
    e13._remember(ctx, texts)
    checks.append(check("ctrl-enter-translates", True, f"sha256={e03.digest([texts[1]])}"))
    _leaves(app, s, checks, s.TEXT_SOURCE_LABEL, "tab-leaves-source-text")
    _leaves(app, s, checks, s.TEXT_RESULT_LABEL, "tab-leaves-translation")
    checks.append(keys.walk(app, "text-tab-stops-named"))
    _cancel(app, s, checks)


def _flow(ctx: RunContext, app: Any, checks: list[Check]) -> None:
    s = ui.strings()
    _listen(app, s, checks)
    _text(ctx, app, s, checks)


def run(ctx: RunContext) -> Row:
    checks: list[Check] = []
    uia_app.close_open(ctx)
    app = uia_app.launch(ctx)
    try:
        _flow(ctx, app, checks)
    finally:
        app.close()
        checks.append(check("settings-baseline-restored", uia_app.settings_reset(ctx)))
    return make_row("E-32", checks, reason="keyboard", method=Method.VIRTUAL_DEVICE)
