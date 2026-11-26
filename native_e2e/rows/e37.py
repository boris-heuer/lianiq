"""E-37, E-38: the running bridge, measured on the cables (CAP-0166 0166-E-04, E-05).

E-37 (AC-07, AC-13, AC-17): on the app of E-34 (``rows.cb``), **Start call bridge**; both lanes
*Listening*. "CABLE-A Output" (the call app's microphone) and "CABLE Output" (the headset) are
recorded. G1 (``conv_de_16k.wav``, "Guten Morgen, das ist ein Test.") is played into *Your
microphone*: the Mandarin translation is heard on cable A and the headset stays silent. A
Mandarin utterance is played into the call speaker cable ("CABLE-B Input"): the run-time
fixture ``conv_zh_16k.wav`` when ``native_e2e.synth`` provides it, else the Mandarin the bridge
just spoke on cable A (kept in memory only). The German translation is heard on the headset,
and cable A stays silent for ``cb.QUIET_S`` after it (the headset bleed into the microphone
is paused). A Windows notification sound does not reach cable A. Both lane lines showed
*Translating…* or *Speaking*; the live text has one turn per direction; the Conversation
transcript stays empty. Latencies (end of the played speech → first translated speech) are
recorded in seconds. One masked screenshot.

E-38 (AC-09, AC-12, AC-17): the Mandarin utterance again; while the German plays, *You → call*
reads "Paused while you hear the translation" and cable A stays silent. Then Settings, **F9**:
both lanes *Stopped*, the four selectors enabled again. The app closes and the S-03 settings
come back. Unplugging the headset (the rest of 0166-E-05) stays a PO row.
"""

from __future__ import annotations

import time
from typing import Any

from native_e2e import audio, fixtures
from native_e2e.context import CABLE_NAMES, RunContext
from native_e2e.evidence.model import Check, Method, Row, Status
from native_e2e.rows import cb, e03, ui
from native_e2e.rows.common import blocked_row, check, make_row

G1 = "conv_de_16k.wav"
VD = Method.VIRTUAL_DEVICE


def _seconds(value: float) -> str:
    return f"{max(0.0, value):.1f}"


def _mandarin(ctx: RunContext, cable: Any, said: tuple[float, float] | None) -> tuple | None:
    path = cb.synth_wav(ctx)
    if path is not None:
        return (*audio.read_wav(path), "synth")
    if said is None:
        return None
    rate, samples = cable.between(said[0] - 0.1, said[1] + 0.1)
    return rate, samples, "loopback"


def _outbound(app, recs, wav, checks: list[Check], watch) -> tuple[float, float] | None:
    end = cb.inject(CABLE_NAMES[0], *wav)
    said = cb.heard(recs["a"], end, ui.MODEL_TIMEOUT_S, watch)
    detail = f"latency_s={_seconds(said[0] - end)}" if said else "timeout"
    checks.append(check("mandarin-on-call-cable", said is not None, detail))
    if said is not None:
        silent = recs["h"].span(end + 0.3, said[1] + cb.SETTLE_S) is None
        checks.append(check("headset-silent-during-outbound", silent))
    return said


def _inbound(app, recs, zh, checks: list[Check], watch) -> tuple[float, float] | None:
    began = time.perf_counter()
    end = cb.inject(cb.B_IN, zh[0], zh[1])
    heard = cb.heard(recs["h"], end, ui.MODEL_TIMEOUT_S, watch)
    detail = f"latency_s={_seconds(heard[0] - end)} source={zh[2]}" if heard else "timeout"
    checks.append(check("german-in-headset", heard is not None, detail))
    if heard is not None:
        silent = cb.quiet(recs["a"], began, heard[1] + cb.QUIET_S)
        checks.append(check("call-cable-silent-during-inbound", silent))
    return heard


def _notification(recs, checks: list[Check]) -> None:
    began = time.perf_counter()
    why = cb.beep()
    if why is not None:
        checks.append(Check("notification-not-on-call-cable", Status.BLOCKED, why))
        return
    silent = cb.quiet(recs["a"], began, began + cb.NOTIFY_S)
    checks.append(check("notification-not-on-call-cable", silent))


def _conversation_empty(app, checks: list[Check]) -> None:
    s = ui.strings()
    shown = ui.select(app, s.NAV_CONVERSATION, s.NAV_REGION)
    texts = e03.view(app.nodes(), s)["texts"] if shown else None
    detail = None if texts is not None else "not-found"
    checks.append(check("conversation-transcript-empty", texts == ["", ""], detail))


def _session(ctx, app, names, wav, checks: list[Check], artifacts: list) -> None:
    t = cb.strings()
    if not (cb.page(app, checks) and cb.assign(app, names, checks) and cb.start(app, checks)):
        return
    seen: list[set] = [set(), set()]

    def watch() -> None:
        for index, text in enumerate(cb.lanes(app.nodes())):
            seen[index].add(text)

    with cb.Recorder(cb.A_OUT) as cable, cb.Recorder(CABLE_NAMES[1]) as headset:
        recs = {"a": cable, "h": headset}
        said = _outbound(app, recs, wav, checks, watch)
        zh = _mandarin(ctx, cable, said)
        if zh is None:
            checks.append(Check("mandarin-source", Status.BLOCKED, "fixture-missing"))
            return
        ctx.state["cb_zh"] = zh  # E-38 plays it again; memory only
        if _inbound(app, recs, zh, checks, watch) is not None:
            _notification(recs, checks)
    items = cb.turns(app.nodes())
    cb.remember(ctx, items)
    out = sum(item.startswith(f"{t.CB_PATH_OUT_NAME} · ") for item in items)
    back = sum(item.startswith(f"{t.CB_PATH_IN_NAME} · ") for item in items)
    moved = {t.CB_LANE_TRANSLATING, t.CB_LANE_SPEAKING}
    checks += [
        check("live-text-one-turn-each-way", (out, back) == (1, 1), f"out={out} in={back}"),
        check("both-lanes-moved", all(lane & moved for lane in seen)),
    ]
    shot, artifact = cb.shot(ctx, app, "screens/e37-running.png", "screenshot-masked")
    checks.append(shot)
    artifacts.append(artifact)
    _conversation_empty(app, checks)


def e37(ctx: RunContext) -> Row:
    names = cb.prepare(ctx)
    if names is None:
        return blocked_row("E-37", cb.BLOCKED)
    wav = fixtures.checked(G1)
    if wav is None:
        return blocked_row("E-37", "fixture-missing")
    fixtures.remember(ctx, G1)
    app = cb.app(ctx)
    checks: list[Check] = []
    artifacts: list = []
    _session(ctx, app, names, audio.read_wav(wav), checks, artifacts)
    return make_row("E-37", checks, artifacts, reason="call-bridge-routing", method=VD)


def _paused_then_f9(ctx, app, names, zh, checks: list[Check], artifacts: list) -> None:
    t, s = cb.strings(), ui.strings()
    if not cb.page(app, checks):
        return
    stop = cb.button(app.nodes(), cb.STOP)
    running = stop is not None and stop.enabled  # E-37 left the bridge running
    if not running and not (cb.assign(app, names, checks) and cb.start(app, checks)):
        return
    with cb.Recorder(cb.A_OUT) as cable, cb.Recorder(CABLE_NAMES[1]) as headset:
        began = time.perf_counter()
        end = cb.inject(cb.B_IN, zh[0], zh[1])
        paused = lambda: cb.lanes(app.nodes())[0] == t.CB_LANE_ECHO_PAUSED
        if not ui.waited(checks, "paused-while-you-hear", paused, ui.MODEL_TIMEOUT_S):
            return
        heard = cb.heard(headset, end, ui.MODEL_TIMEOUT_S)
        until = (heard[1] if heard else time.perf_counter()) + cb.QUIET_S
        checks.append(check("nothing-sent-while-paused", cb.quiet(cable, began, until)))
    if not ui.select(app, s.NAV_SETTINGS, s.NAV_REGION):
        checks.append(check("settings-page", False))
        return
    app.keys("{F9}")
    stopped = lambda: cb.lanes(app.nodes()) == (t.CB_LANE_STOPPED, t.CB_LANE_STOPPED)
    if not (cb.page(app, checks) and ui.waited(checks, "f9-stops-both-lanes", stopped)):
        return
    combos = [ui.find(app.nodes(), label, "ComboBox") for label in cb.roles().values()]
    unlocked = all(combo is not None and combo.enabled for combo in combos)
    checks.append(check("selectors-unlocked", unlocked))
    cb.remember(ctx, cb.turns(app.nodes()))  # the E-38 turn too
    shot, artifact = cb.shot(ctx, app, "screens/e38-after-f9.png", "screenshot-masked")
    checks.append(shot)
    artifacts.append(artifact)


def e38(ctx: RunContext) -> Row:
    names = cb.prepare(ctx)
    checks: list[Check] = []
    artifacts: list = []
    zh = ctx.state.pop("cb_zh", None)
    try:
        if names is None:
            return blocked_row("E-38", cb.BLOCKED)
        zh = zh or _mandarin(ctx, None, None)
        if zh is None:
            checks.append(Check("mandarin-source", Status.BLOCKED, "fixture-missing"))
        else:
            _paused_then_f9(ctx, cb.app(ctx), names, zh, checks, artifacts)
    finally:
        if ctx.state.get("app") is not None or names is not None:
            cb.finish(ctx, checks)
    return make_row("E-38", checks, artifacts, reason="call-bridge-pause-stop", method=VD)
