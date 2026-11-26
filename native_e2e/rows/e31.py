"""E-31: keyboard only through sidebar, Conversation, Settings and Ctrl+1…7 (automated-po-rows).

The keyboard parts of CAP-0168 E-09 (AC-28) and CAP-0167 E-08 (AC-22) without a hearing
judgment: UI Automation reads the focused element after each key. On the image models the
row starts its own app and walks the Tab cycle of Conversation (sidebar, workspace with the
voice row, session strip): every stop must have a name. In the voice row the first enabled
switch ("Speak {language}") is focused with Tab; Space toggles it and Space again restores
it. The first **Voice options…** button ("Voice options for {language}") is focused; Enter
opens its dialog ("Voice options — {language}"); the dialog's Tab cycle is walked and Escape
closes it (when Enter does not open it, Space opens it for the walk, and the Enter check
stays failed). Settings (with *Voice output*): the Tab cycle is walked; **Export…** is
focused, Space opens "Export diagnostics", Escape cancels it and the focus is back on
**Export…**. Last, Ctrl+2…Ctrl+7 and Ctrl+1 each select their sidebar entry.

Only counts and control types are stored, never a name. The app is closed and the settings
file is reset to the S-03 baseline (the voice switch was written twice).
"""

from __future__ import annotations

from typing import Any

from native_e2e import uia_app
from native_e2e.context import RunContext
from native_e2e.evidence.model import Check, Row
from native_e2e.rows import e03, keys, ui
from native_e2e.rows.common import check, make_row

PAGES = 7  # the sidebar entries Ctrl+1…Ctrl+7 select (lianiq.ui.main_window)


def _switch_state(app: Any, name: str) -> bool | None:
    node = ui.find(app.nodes(), name, "CheckBox")
    return node.selected if node is not None else None


def _space(app: Any, s: Any, checks: list[Check]) -> None:
    label = "space-toggles-voice-switch"
    switch = next((n for n in e03._voice_switches(app.nodes(), s) if n.enabled), None)
    if switch is None:
        checks.append(check(label, False, "not-found"))
        return
    if keys.tab_to(app, keys.named(switch.name, "CheckBox")) is None:
        checks.append(check(label, False, "not-a-tab-stop"))
        return
    before = bool(switch.selected)
    app.keys("{SPACE}")
    toggled = keys.became(lambda: _switch_state(app, switch.name) is (not before))
    app.keys("{SPACE}")
    restored = keys.became(lambda: _switch_state(app, switch.name) is before)
    detail = None if toggled and restored else ("not-restored" if toggled else "not-toggled")
    checks.append(check(label, toggled and restored, detail))


def _voice_options(app: Any, s: Any, checks: list[Check]) -> None:
    prefix = s.VOICE_OPTIONS_NAME.split("{", 1)[0]
    button = next(
        (n for n in app.nodes() if n.visible and n.enabled and n.name.startswith(prefix)), None
    )
    if button is None or keys.tab_to(app, keys.named(button.name)) is None:
        detail = "not-found" if button is None else "not-a-tab-stop"
        checks.append(check("enter-opens-voice-options", False, detail))
        return
    title = s.VOICE_OPTIONS_TITLE.format(language=button.name[len(prefix) :])
    if not keys.dialog(app, checks, "voice-options", "enter", title):
        keys.dialog(app, checks, "voice-options", "space", title)  # the walk still runs


def _settings(app: Any, s: Any, checks: list[Check]) -> None:
    if not ui.select(app, s.NAV_SETTINGS, s.NAV_REGION):
        checks.append(check("settings-tab-stops-named", False, "not-selected"))
        return
    checks.append(keys.walk(app, "settings-tab-stops-named"))
    if keys.tab_to(app, keys.named(s.DIAG_EXPORT, "Button")) is None:
        checks.append(check("space-opens-export-dialog", False, "not-a-tab-stop"))
        return
    if keys.dialog(app, checks, "export-dialog", "space", s.DIAG_EXPORT_TITLE, walked=False):
        back = keys.became(lambda: keys.focused_is(app, s.DIAG_EXPORT))
        checks.append(check("focus-returns-to-export", back))


def _ctrl_digits(app: Any, s: Any, checks: list[Check]) -> None:
    entries = [node.name for node in ui.sidebar(app.nodes(), s.NAV_REGION)]

    def selected(name: str) -> bool:
        return any(n.name == name and n.selected for n in ui.sidebar(app.nodes(), s.NAV_REGION))

    switched = 0
    for index in (*range(2, PAGES + 1), 1):
        if index > len(entries):
            continue
        app.keys(f"^{index}")
        switched += keys.became(lambda index=index: selected(entries[index - 1]))
    ok = len(entries) == PAGES and switched == PAGES
    checks.append(check("ctrl-1-7-switch-pages", ok, f"switched={switched}/{len(entries)}"))


def _flow(app: Any, checks: list[Check]) -> None:
    s = ui.strings()
    if ui.select(app, s.NAV_CONVERSATION, s.NAV_REGION):
        checks.append(keys.walk(app, "conversation-tab-stops-named"))
        _space(app, s, checks)
        _voice_options(app, s, checks)
    else:
        checks.append(check("conversation-tab-stops-named", False, "not-selected"))
    _settings(app, s, checks)
    _ctrl_digits(app, s, checks)


def run(ctx: RunContext) -> Row:
    checks: list[Check] = []
    uia_app.close_open(ctx)
    app = uia_app.launch(ctx)
    try:
        _flow(app, checks)
    finally:
        app.close()
        checks.append(check("settings-baseline-restored", uia_app.settings_reset(ctx)))
    return make_row("E-31", checks, reason="keyboard")
