"""E-40: an English ↔ Mandarin Conversation through the cable (english-mandarin-pair 9-E-04).

Blocked with ``english-packs-missing`` like E-39 when the image lacks an English pack. Before
any app starts ``speech_pair`` synthesises E1 (English) and Z1 (Mandarin) with the image's
voices into the job's temp folder; a failed synthesis fails the row (``speech-synthesized``,
exception type only). E-40 closes an app left open and starts its own (image models).
Settings › Audio devices: "CABLE Output" as Microphone (``name_matches`` only); Conversation:
*Language pair* "English ↔ Mandarin (Simplified)", direction Automatic, every voice switch
off (as E-03). **Start** (F8), wait for "Conversation running" (300 s), play E1 into
"CABLE Input" and wait for an English → Mandarin turn, then Z1 and a Mandarin → English turn,
each recorded once two consecutive reads agree. A turn is a *Transcript* row with source
English and target Mandarin (Simplified) and a translation (or the reverse); the row stores
the turn count per direction and the transcript SHA-256, never a text. One masked
screenshot (the *Transcript* list masked); F9 stops the session. In ``finally`` the app is closed,
the settings baseline restored (``settings_reset``) and the WAVs deleted.

Pass: at least one translation each way. Texts go to ``ctx.secrets`` and
``ctx.state["transcripts"]`` (screenshot masking), as in E-03.
"""

from __future__ import annotations

from typing import Any

from native_e2e import audio, speech_pair, uia_app
from native_e2e.context import RunContext
from native_e2e.evidence.model import Check, Method, Row
from native_e2e.rows import e03, e39, ui
from native_e2e.rows.common import blocked_row, check, make_row

SCREEN = "screens/e40-conversation.png"
ENGLISH, MANDARIN = "en", "zh-Hans"


def display(language: str) -> str:
    from lianiq.languages import BUILTIN_REGISTRY

    return BUILTIN_REGISTRY.display_name(language)


def turns(texts: list[str] | None, source: str, target: str) -> int:
    """*Transcript* rows from ``source`` to ``target`` with a translation."""
    names = (display(source), display(target))
    rows = [e03.turn_parts(text) for text in texts or []]
    return sum(
        1
        for parts in rows
        if parts is not None and (parts[0], parts[2]) == names and parts[3].strip()
    )


def _settled(app: Any, s: Any, source: str, target: str) -> dict[str, Any]:
    """The view once it has a ``source`` → ``target`` turn and two reads agree."""
    last: list[dict[str, Any]] = []

    def probe() -> dict[str, Any] | None:
        current = e03.view(app.nodes(), s)
        stable = bool(last) and last[-1] == current
        last[:] = [current]
        return current if stable and turns(current["texts"], source, target) else None

    return ui.wait(probe, ui.MODEL_TIMEOUT_S)


def _choose_pair(app: Any, s: Any, checks: list[Check]) -> bool:
    wanted = e39.pair_name(ENGLISH, MANDARIN)
    if not ui.select(app, s.NAV_CONVERSATION, s.NAV_REGION):
        checks.append(check("pair-english-mandarin", False, "not-selected"))
        return False
    combo = ui.find(app.nodes(), s.PAIR_LABEL, "ComboBox")
    try:
        if combo is not None and combo.value != wanted:
            app.choose(combo, wanted)
        ui.wait_nodes(app, lambda nodes: e03.view(nodes, s)["pair"] == wanted)
    except Exception:  # noqa: BLE001 - not listed (UIA error) or timeout
        checks.append(check("pair-english-mandarin", False, "not-selected"))
        return False
    checks.append(check("pair-english-mandarin", True))
    automatic = s.ROUTING_AUTOMATIC.format(a=display(ENGLISH), b=display(MANDARIN))
    direction = e03.view(app.nodes(), s)["direction"]
    checks.append(check("direction-automatic", direction == automatic))
    return direction == automatic


def _turn(app, s, checks: list[Check], wav, source: str, target: str) -> dict | None:
    name = f"{source}-to-{target}-turn".lower()
    audio.play_into_cable(wav)
    try:
        view = _settled(app, s, source, target)
    except TimeoutError:
        checks.append(check(name, False, "timeout"))
        return None
    checks.append(check(name, True, f"turns={turns(view['texts'], source, target)}"))
    return view


def _session(ctx: RunContext, app: Any, wavs: list, checks: list[Check], artifacts: list) -> None:
    s = ui.strings()
    running = s.SESSION_RUNNING.format(mode=s.NAV_CONVERSATION)
    if not e03._cable_microphone(app, s, checks) or not _choose_pair(app, s, checks):
        return
    if not e03._voice_output_off(app, s, checks):
        return
    app.keys("{F8}")
    probe = lambda: ui.shows(app.nodes(), running)
    if not ui.waited(checks, "session-running", probe, ui.MODEL_TIMEOUT_S):
        return
    view = _turn(app, s, checks, wavs[0], ENGLISH, MANDARIN)
    view = view and _turn(app, s, checks, wavs[1], MANDARIN, ENGLISH)
    if view:
        e03._remember(ctx, view["texts"])
        checks.append(check("transcript-sha256", True, f"sha256={e03.digest(view['texts'])}"))
        shot, artifact = ui.screenshot(ctx, app, SCREEN, "screenshot-masked")
        checks.append(shot)
        artifacts.append(artifact)
    app.keys("{F9}")
    gone = lambda: not ui.shows(app.nodes(), running)
    ui.waited(checks, "stopped-with-f9", gone)


def run(ctx: RunContext) -> Row:
    absent = e39.packs_missing(ctx)
    if absent:
        return blocked_row("E-40", e39.MISSING, f"missing={absent}")
    try:
        wavs = speech_pair.speech_wavs(ctx)
    except Exception as error:  # noqa: BLE001 - no voice or engine: the row cannot play
        checks = [check("speech-synthesized", False, type(error).__name__)]
        return make_row("E-40", checks, reason="english-speech", method=Method.VIRTUAL_DEVICE)
    checks: list[Check] = [check("speech-synthesized", True, f"files={len(wavs)}")]
    artifacts: list = []
    try:
        uia_app.close_open(ctx)  # an app left open by an earlier row: E-40 needs its own
        app = uia_app.launch(ctx)
        try:
            _session(ctx, app, wavs, checks, artifacts)
        finally:
            app.close()
    finally:
        uia_app.settings_reset(ctx)
        speech_pair.discard(wavs)
    return make_row(
        "E-40", checks, artifacts, reason="english-conversation", method=Method.VIRTUAL_DEVICE
    )
