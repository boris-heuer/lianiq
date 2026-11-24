"""E-27: voice output readiness on the image models (CAP-0167 e2e plan E-01, E-06).

The local settings are reset to the S-03 baseline first (no stored voice choice), then the
row starts its own app (image models, both voices ready). Conversation: no *Voice output*
checkbox (the voice row is a group of that name, never a CheckBox); the switches "Speak
German" and "Speak Mandarin (Simplified)" are enabled and on, and each state label reads
"{voice} · Ready"; before any Start **Replay** is disabled with the tooltip "Nothing to
replay yet". Settings › Voice output shows the same two switches on and the Call Bridge /
Meeting hint; Settings › Diagnostics lists "Voice German: Ready" and "Voice Mandarin
(Simplified): Ready". One masked screenshot of Conversation. The row changes no setting.
"""

from __future__ import annotations

from native_e2e import uia_app
from native_e2e.context import RunContext
from native_e2e.evidence.model import Check, Row
from native_e2e.rows import ui, voice
from native_e2e.rows.common import check, make_row
from native_e2e.rows.voice import GERMAN, MANDARIN
from native_e2e.uia import Node

SCREEN = "screens/e27-conversation.png"


def _no_checkbox(nodes: list[Node], s) -> bool:
    return not any(
        n.visible and n.control_type == "CheckBox" and n.name == s.VOICE_SECTION for n in nodes
    )


def _replay_empty(nodes: list[Node], s) -> bool:
    button = ui.find(nodes, s.VOICE_REPLAY, "Button")
    return button is not None and not button.enabled and s.VOICE_REPLAY_EMPTY in button.description


def _page(app, s, label: str, checks: list[Check], probe, name: str) -> bool:
    if not ui.select(app, label, s.NAV_REGION):
        checks.append(check(name, False, "not-selected"))
        return False
    return ui.waited(checks, name, lambda: probe(app.nodes()))


def _rows(ctx, app, checks: list[Check], artifacts: list) -> None:
    s = ui.strings()

    def ready(nodes) -> bool:
        states = all(voice.state_ready(nodes, s, language) for language in (GERMAN, MANDARIN))
        return voice.switches_on(nodes, s) and states

    if not _page(app, s, s.NAV_CONVERSATION, checks, ready, "switches-on-ready"):
        return
    nodes = app.nodes()
    checks += [
        check("no-voice-output-checkbox", _no_checkbox(nodes, s)),
        check("replay-disabled-nothing-yet", _replay_empty(nodes, s)),
    ]
    shot, artifact = ui.screenshot(ctx, app, SCREEN, "screenshot-conversation-masked")
    checks.append(shot)
    artifacts.append(artifact)

    def mirror(nodes) -> bool:
        return voice.switches_on(nodes, s) and ui.shows(nodes, s.VOICE_REQUIREMENTS_HINT)

    if not _page(app, s, s.NAV_SETTINGS, checks, mirror, "settings-switches-and-hint"):
        return
    rows = [voice.readiness_row(s, language, s.DIAG_READY) for language in (GERMAN, MANDARIN)]
    ui.waited(
        checks, "diagnostics-voices-ready", lambda: all(r in voice.readiness(app, s) for r in rows)
    )


def run(ctx: RunContext) -> Row:
    uia_app.close_open(ctx)
    checks: list[Check] = [check("settings-baseline", uia_app.settings_reset(ctx))]
    artifacts: list = []
    app = uia_app.launch(ctx)
    try:
        _rows(ctx, app, checks, artifacts)
    finally:
        app.close()
    return make_row("E-27", checks, artifacts, reason="voice-readiness")
