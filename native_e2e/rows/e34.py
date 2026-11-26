"""E-34, E-35: the Call Bridge page defaults and the same-cable refusal (CAP-0166 0166-E-01, E-02).

E-34 (CAP-0166 AC-01, AC-02): the local settings lose their ``call_bridge`` block (e2e plan
D-05), a fresh app starts (it stays open for E-35..E-38, see ``rows.cb``) and **Call Bridge**
is opened. Pass rules: no *Enable* checkbox; the experimental note and the *Real-call
checklist* link; both path boxes (*You → call*, *Call → you*); the readiness list names all four
roles with "select a device"; **Start call bridge** disabled; both level meters show no signal;
the app process has no WASAPI render session (no stream opened). One masked screenshot.

E-35 (AC-02, AC-03): *Your microphone* "CABLE Output", the call microphone cable "CABLE-A
Input", the call speaker cable "CABLE-A Output" (the same cable) and *Your headphones* "CABLE
Input": the readiness list shows "Both call cables are the same virtual cable…" and Start is
disabled. Then the call speaker cable becomes "CABLE-B Output": the readiness list empties and
Start is enabled (once the models are ready, 300 s). A masked screenshot of each state.
"""

from __future__ import annotations

from typing import Any

from native_e2e import audio_sessions
from native_e2e.context import RunContext
from native_e2e.evidence.model import Check, Row
from native_e2e.rows import cb, ui
from native_e2e.rows.common import blocked_row, check, make_row
from native_e2e.uia import Node


def _reasons(nodes: list[Node]) -> list[str]:
    """The shown lines of the readiness list *Before you can start*."""
    title = cb.strings().CB_READINESS
    return [n.name for n in nodes if n.visible and n.name and title in n.parents]


def _no_enable_box(nodes: list[Node], s: Any) -> bool:
    return not any(
        n.visible and n.control_type == "CheckBox" and n.name.casefold().startswith("enable")
        for n in nodes
        if s.NAV_REGION not in n.parents
    )


def _still(nodes: list[Node], t: Any) -> bool:
    """Both meters present; neither caption reports a signal or clipping."""
    bars = [ui.find(nodes, name, "ProgressBar") for name in (t.CB_LEVEL_MIC, t.CB_LEVEL_CALL)]
    loud = {
        f"{meter}: {caption}"
        for meter in (t.CB_LEVEL_MIC, t.CB_LEVEL_CALL)
        for caption in (t.CB_LEVEL_SIGNAL, t.CB_LEVEL_CLIPPING)
    }
    return None not in bars and not any(n.visible and n.name in loud for n in nodes)


def _render_sessions(app: Any) -> int | None:
    try:
        return len(audio_sessions.render_pids() & set(app.pids()))
    except Exception:  # noqa: BLE001 - sessions unreadable: the check fails, named
        return None


def _defaults(ctx: RunContext, app: Any, checks: list[Check], artifacts: list) -> None:
    s, t = ui.strings(), cb.strings()
    nodes = app.nodes()
    boxes = [
        any(n.visible and n.name.startswith(f"{p} · ") for n in nodes)
        for p in (t.CB_PATH_OUT_NAME, t.CB_PATH_IN_NAME)
    ]
    wanted = {t.CB_R_SELECT.format(role=label) for label in cb.roles().values()}
    start = cb.button(nodes, cb.START)
    sessions = _render_sessions(app)
    checks += [
        check("no-enable-checkbox", _no_enable_box(nodes, s)),
        check("experimental-note", ui.shows(nodes, t.CB_EXPERIMENTAL)),
        check("checklist-link", ui.shows(nodes, t.CB_CHECKLIST_LINK)),
        check("both-path-boxes", all(boxes)),
        check("four-select-a-device", wanted <= set(_reasons(nodes))),
        check("start-disabled", start is not None and not start.enabled),
        check("level-meters-still", _still(nodes, t)),
        check("no-stream-opened", sessions == 0, f"render_sessions={sessions}"),
    ]
    shot, artifact = cb.shot(ctx, app, "screens/e34-defaults.png", "screenshot-masked")
    checks.append(shot)
    artifacts.append(artifact)


def e34(ctx: RunContext) -> Row:
    if cb.prepare(ctx) is None:
        return blocked_row("E-34", cb.BLOCKED)
    cb.fresh_settings(ctx)
    app = cb.app(ctx, fresh=True)
    checks: list[Check] = []
    artifacts: list = []
    if cb.page(app, checks):
        _defaults(ctx, app, checks, artifacts)
    return make_row("E-34", checks, artifacts, reason="call-bridge-defaults")


def e35(ctx: RunContext) -> Row:
    names = cb.prepare(ctx)
    if names is None:
        return blocked_row("E-35", cb.BLOCKED)
    t = cb.strings()
    app = cb.app(ctx)
    checks: list[Check] = []
    artifacts: list = []
    if cb.page(app, checks) and cb.assign(app, names, checks, speaker="a_out"):
        nodes = app.nodes()
        checks += [
            check("same-cable-listed", t.CB_R_SAME_CABLE in _reasons(nodes)),
            check("start-disabled-same-cable", not cb.start_enabled(nodes)),
        ]
        shot, artifact = cb.shot(ctx, app, "screens/e35-same-cable.png", "screenshot-same-cable")
        checks.append(shot)
        artifacts.append(artifact)
        if cb.assign(app, names, checks):
            probe = lambda: (n := app.nodes()) and not _reasons(n) and cb.start_enabled(n)
            if ui.waited(checks, "readiness-empty-start-enabled", probe, ui.MODEL_TIMEOUT_S):
                shot, artifact = cb.shot(ctx, app, "screens/e35-ready.png", "screenshot-ready")
                checks.append(shot)
                artifacts.append(artifact)
    return make_row("E-35", checks, artifacts, reason="call-bridge-cables")
