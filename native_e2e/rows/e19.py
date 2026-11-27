"""E-19: an offline Conversation on imported packs (CAP-0171 e2e plan E-09, E-04).

Runs inside the E-18 group (``e18.run`` calls ``session`` on its app and scratch models, the
pair's packs *Validated*); ``run`` returns the row E-18 left in ``ctx.state["e19_row"]``.
``conv_de_16k.wav`` (D-04 "Guten Morgen, das ist ein Test.") must match its pin
(``fixtures.checked``; else ``blocked`` ``fixture-missing``); its text goes to
``ctx.secrets``. Microphone "CABLE Output" (E-18 already selected it). Conversation **Start**
(F8); while the models load every shown warm-up text ("Loading models …", the status bar's
"Loading the models …"; hard-coded in ``ui/workspaces/conversation_flow.py``) is read: at
least one must be seen and none may show a percentage. After "Conversation running" the WAV
is played into "CABLE Input"; a turn in the *Transcript* list must appear (300 s;
SHA-256 only, the texts go to ``ctx.secrets``); F9 must end the session. The app
interpreter's non-loopback connection count since the row started must be 0. One masked
screenshot after the stop (the *Transcript* list masked).
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from native_e2e import audio, fixtures, uia
from native_e2e.evidence.model import Check, Method, Row
from native_e2e.rows import e03, provisioning, s04, ui
from native_e2e.rows.common import blocked_row, check, make_row

if TYPE_CHECKING:
    from native_e2e.context import RunContext

FIXTURE = "conv_de_16k.wav"
WARM_UP = "Loading"  # the start of both warm-up texts (not in lianiq/ui/strings.py)
PERCENT = re.compile(r"\d\s*%")
SCREEN = "screens/e19-after-stop.png"
KEY = "e19_row"


def warm_up_texts(nodes) -> list[str]:
    return [node.name for node in nodes if node.visible and node.name.startswith(WARM_UP)]


def _start(app: Any, s: Any, running: str, checks: list[Check]) -> bool:
    if not ui.select(app, s.NAV_CONVERSATION, s.NAV_REGION):
        checks.append(check("session-running", False, "not-selected"))
        return False
    seen: list[str] = []
    app.keys("{F8}")

    def started() -> bool:
        nodes = app.nodes()
        seen.extend(warm_up_texts(nodes))
        return ui.shows(nodes, running)

    try:
        uia.wait_for(started, ui.MODEL_TIMEOUT_S, ui.POLL_S)
    except TimeoutError:
        checks.append(check("session-running", False, "timeout"))
        return False
    checks.append(check("session-running", True))
    percent = any(PERCENT.search(text) for text in seen)
    ok = bool(seen) and not percent
    detail = f"seen={len(seen)} percentage={str(percent).lower()}"
    checks.append(check("warm-up-without-percentage", ok, detail))
    return True


def session(ctx: RunContext, app: Any) -> Row:
    path = fixtures.checked(FIXTURE)
    if path is None:
        return blocked_row("E-19", "fixture-missing", FIXTURE)
    fixtures.remember(ctx, FIXTURE)
    s = ui.strings()
    running = s.SESSION_RUNNING.format(mode=s.NAV_CONVERSATION)
    checks: list[Check] = [check("fixture-sha256", True)]
    artifacts: list = []
    since = s04.now_iso()
    if _start(app, s, running, checks):
        audio.play_into_cable(path)
        if ui.waited(
            checks, "translation-turn", lambda: e03.has_turn(app.nodes(), s), ui.MODEL_TIMEOUT_S
        ):
            texts = e03.view(app.nodes(), s)["texts"] or []
            e03._remember(ctx, texts)
            checks.append(check("transcript-sha256", True, f"sha256={e03.digest(texts)}"))
            app.keys("{F9}")
            if ui.waited(checks, "stopped", lambda: e03._strip_gone(app.nodes(), s, running)):
                shot, artifact = provisioning.shot(ctx, app, SCREEN, "screenshot-masked")
                checks.append(shot)
                artifacts.append(artifact)
    count = s04.count_since(ctx, since)
    checks.append(check("connection-count-0", count == 0, f"count={count}"))
    return make_row(
        "E-19", checks, artifacts, reason="offline-conversation", method=Method.VIRTUAL_DEVICE
    )


def run(ctx: RunContext) -> Row:
    row = ctx.state.pop(KEY, None)
    return row if row is not None else blocked_row("E-19", "e18-group-not-run")
