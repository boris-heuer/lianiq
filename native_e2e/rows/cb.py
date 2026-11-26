"""Shared steps of the Call Bridge rows E-34..E-38 (CAP-0166 0166-E-01..E-05; spec §2.2, §2.3).

Cable roles (docs/native-e2e-rows.md): VB-Cable is the headset ("CABLE Output" *Your
microphone*, "CABLE Input" *Your headphones*), "CABLE-A Input" the call microphone cable (the
rows record "CABLE-A Output") and "CABLE-B Output" the call speaker cable (the rows play into
"CABLE-B Input"). Without VB-Cable A+B every row is ``blocked`` (``cable-ab-missing``).
E-34 starts the shared app (``ctx.state["app"]``), E-38 closes it and restores the settings.
``Recorder`` keeps samples in memory: only spans, latencies and counts reach the evidence.
"""

from __future__ import annotations

import json
import time
from typing import Any

from native_e2e import audio, screens, uia, uia_app
from native_e2e.context import CABLE_AB_NAMES, RunContext
from native_e2e.evidence.model import Artifact, Check
from native_e2e.rows import ui
from native_e2e.rows.common import check
from native_e2e.uia import Node

A_IN, A_OUT, B_IN, B_OUT = CABLE_AB_NAMES
BLOCKED = "cable-ab-missing"
# The Start/Stop labels are set in lianiq/ui/call_bridge_panel.py, not in a strings module.
START, STOP = "Start call bridge", "Stop call bridge"
# role key → (WASAPI name prefix, flow); "speaker" is chosen per row (B, or A for E-35).
ENDPOINTS = {
    "mic": (audio.CABLE_OUTPUT, "input"),
    "headphones": (audio.CABLE_INPUT, "output"),
    "a_in": (A_IN, "output"),
    "a_out": (A_OUT, "input"),
    "b_in": (B_IN, "output"),
    "b_out": (B_OUT, "input"),
}
SETTLE_S = 1.0  # speech has ended once the cable stayed quiet this long
QUIET_S = 8.0  # measurement window: no speech may reach a cable that must stay silent
NOTIFY_S = 3.0
_ASTERISK = 0x40  # MB_ICONASTERISK: the Windows "Asterisk" notification sound


def strings() -> Any:
    from lianiq.ui import strings_call_bridge as texts

    return texts


def endpoints() -> dict[str, str] | None:
    """The WASAPI names (as the app lists them) of the six endpoints; ``None`` if any is
    missing (the VB-Cable A+B image prerequisite, spec §2.3)."""
    try:
        names = {key: audio.wasapi_name(*spec) for key, spec in ENDPOINTS.items()}
    except Exception:  # noqa: BLE001 - no PortAudio or no devices: the cables are missing
        return None
    return names if all(names.values()) else None  # type: ignore[return-value]


def prepare(ctx: RunContext) -> dict[str, str] | None:
    """The endpoint names, also added to the redaction secrets (never stored)."""
    names = endpoints()
    for name in (*CABLE_AB_NAMES, *(names or {}).values()):
        if name not in ctx.secrets:
            ctx.secrets.append(name)
    return names


def fresh_settings(ctx: RunContext) -> None:
    """e2e plan D-05: the local settings without their ``call_bridge`` block."""
    path = ctx.local_settings
    if path.is_file():
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.pop("call_bridge", None) is not None:
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def app(ctx: RunContext, fresh: bool = False) -> Any:
    """The rows' shared app; ``fresh`` closes any app left open and starts a new one."""
    if fresh:
        uia_app.close_open(ctx)
    if ctx.state.get("app") is None:
        ctx.state["app"] = uia_app.launch(ctx)
    return ctx.state["app"]


def finish(ctx: RunContext, checks: list[Check]) -> None:
    """Close the shared app and restore the S-03 settings baseline."""
    uia_app.close_open(ctx)
    checks.append(check("settings-reset", uia_app.settings_reset(ctx)))


def page(app: Any, checks: list[Check]) -> bool:
    s = ui.strings()
    ok = ui.select(app, s.NAV_CALL_BRIDGE, s.NAV_REGION)
    checks.append(check("call-bridge-page", ok))
    return ok


def roles() -> dict[str, str]:
    t = strings()
    return {
        "mic": t.CB_ROLE_LOCAL_MIC,
        "call_mic": t.CB_ROLE_CALL_MIC,
        "speaker": t.CB_ROLE_CALL_SPEAKER,
        "headphones": t.CB_ROLE_HEADPHONES,
    }


def _value(app: Any, label: str) -> str | None:
    combo = ui.find(app.nodes(), label, "ComboBox")
    return combo.value if combo is not None else None


def choose(app: Any, label: str, name: str) -> bool:
    """Select ``name`` in the role combo ``label`` (already selected counts)."""
    try:
        combo = ui.find(app.nodes(), label, "ComboBox")
        if combo is None:
            return False
        if combo.value != name:
            app.choose(combo, name)
        ui.wait(lambda: _value(app, label) == name)
    except Exception:  # noqa: BLE001 - not listed (UIA/pywinauto error) or timeout
        return False
    return True


def assign(app: Any, names: dict[str, str], checks: list[Check], speaker: str = "b_out") -> bool:
    """The four roles: headset mic, cable A playback, the ``speaker`` side, headphones."""
    label = roles()
    wanted = (
        (label["mic"], names["mic"]),
        (label["call_mic"], names["a_in"]),
        (label["speaker"], names[speaker]),
        (label["headphones"], names["headphones"]),
    )
    chosen = sum(choose(app, role, name) for role, name in wanted)
    checks.append(check(f"devices-selected-{speaker}", chosen == 4, f"selected={chosen}"))
    return chosen == 4


def _in_box(node: Node, path_name: str) -> bool:
    return any(parent.startswith(f"{path_name} · ") for parent in node.parents)


def prefixed(nodes: list[Node], prefix: str, path_name: str) -> str | None:
    """The text after ``prefix: `` of the shown element in the path box ``path_name``."""
    head = f"{prefix}: "
    for node in nodes:
        if node.visible and node.name.startswith(head) and _in_box(node, path_name):
            return node.name[len(head) :]
    return None


def lanes(nodes: list[Node]) -> tuple[str | None, str | None]:
    """The lane status texts of *You → call* and *Call → you*."""
    t = strings()
    return tuple(  # type: ignore[return-value]
        prefixed(nodes, t.CB_LANE_STATUS, path) for path in (t.CB_PATH_OUT_NAME, t.CB_PATH_IN_NAME)
    )


def button(nodes: list[Node], name: str) -> Node | None:
    return ui.find(nodes, name, "Button")


def start_enabled(nodes: list[Node]) -> bool:
    found = button(nodes, START)
    return found is not None and found.enabled


def start(app: Any, checks: list[Check]) -> bool:
    """**Start call bridge** once readiness allows it (models: 300 s), then both lanes listen."""
    if not ui.waited(
        checks, "start-enabled", lambda: start_enabled(app.nodes()), ui.MODEL_TIMEOUT_S
    ):
        return False
    app.press(button(app.nodes(), START))
    listening = strings().CB_LANE_LISTENING
    probe = lambda: lanes(app.nodes()) == (listening, listening)
    return ui.waited(checks, "both-lanes-listening", probe, ui.MODEL_TIMEOUT_S)


def turns(nodes: list[Node]) -> list[str]:
    """The live text items (accessible text "<direction> · <original> · <translation>")."""
    title = strings().CB_TEXT_TITLE
    return [n.name for n in nodes if n.control_type == "ListItem" and title in n.parents]


def remember(ctx: RunContext, items: list[str]) -> None:
    """Every original and translation of the live text goes to the secrets and the mask."""
    parts = [part for item in items for part in item.split(" · ")[1:]]
    needles = ui.transcript_needles(parts)
    ctx.state.setdefault("transcripts", []).extend(needles)
    ctx.secrets.extend(needle for needle in needles if needle not in ctx.secrets)


def shot(ctx: RunContext, app: Any, relative: str, name: str) -> tuple[Check, Artifact]:
    """A masked screenshot: endpoint names, the four role combos and the whole live text."""
    names = [*audio.endpoint_names(), *ui.transcript_needles(ctx.state.get("transcripts", []))]
    fields = (*screens.TRANSCRIPT_FIELDS, strings().CB_TEXT_TITLE)
    artifact, masked = screens.capture(ctx, app, relative, names, tuple(roles().values()), fields)
    return check(name, True, f"masked={masked}"), artifact


# Cables ------------------------------------------------------------------------------


def _index(prefix: str, kind: str) -> tuple[int, int]:
    sd = audio._sd()
    rows = audio.devices()
    found = audio.pick_index(rows, prefix, kind, int(sd.default.hostapi))
    index = audio._required(found, prefix.split()[-1].casefold())
    return index, int(float(rows[index]["default_samplerate"]))


def play(prefix: str, rate: int, frames: Any) -> None:
    """Play ``frames`` into the render endpoint ``prefix…``; returns when it has ended."""
    index, _rate = _index(prefix, "output")
    audio._sd().play(frames, rate, device=index, blocking=True)


def inject(prefix: str, rate: int, frames: Any) -> float:
    """Play ``frames``; the ``perf_counter`` time its speech ended (or the playback, if silent)."""
    began = time.perf_counter()
    play(prefix, rate, frames)
    span = audio.speech_span(frames[:, 0] if getattr(frames, "ndim", 1) > 1 else frames, rate)
    return began + span[1] if span else time.perf_counter()


def beep() -> str | None:
    """Play the Windows notification sound; why not (``default-render-is-call-cable``)."""
    sd = audio._sd()
    apis = [api for api in sd.query_hostapis() if "wasapi" in str(api["name"]).casefold()]
    index = int(apis[0]["default_output_device"]) if apis else -1  # the Windows default
    if index >= 0 and str(sd.query_devices(index)["name"]).startswith((A_IN, B_IN)):
        return "default-render-is-call-cable"
    import winsound

    winsound.MessageBeep(_ASTERISK)
    return None


def synth_wav(ctx: RunContext) -> Any:
    """The run-time Mandarin fixture (``native_e2e.synth``, when present), else ``None``."""
    try:
        from native_e2e import synth
    except ImportError:
        return None
    return synth.speech_wav(ctx, "conv_zh_16k.wav")


class Recorder(audio.CableRecorder):
    """``CableRecorder`` on the capture endpoint ``prefix…``, on the ``perf_counter`` clock."""

    def __init__(self, prefix: str) -> None:
        super().__init__()
        self.prefix = prefix
        self.began = 0.0

    def start(self) -> Recorder:
        index, self.rate = _index(self.prefix, "input")
        sd = audio._sd()
        stream = sd.InputStream(
            samplerate=self.rate, channels=1, device=index, callback=self._callback
        )
        stream.start()
        self._stream, self.began = stream, time.perf_counter()
        return self

    def between(self, since: float, until: float | None = None) -> tuple[int, Any]:
        import numpy

        with self._lock:
            samples = numpy.concatenate(self._chunks) if self._chunks else numpy.zeros(0)
        first = max(0, int((since - self.began) * self.rate))
        last = None if until is None else max(first, int((until - self.began) * self.rate))
        return self.rate, samples[first:last]

    def span(self, since: float, until: float | None = None) -> tuple[float, float] | None:
        """``perf_counter`` (first, last) speech of the recording between ``since`` and ``until``."""
        rate, samples = self.between(since, until)
        found = audio.speech_span(samples, rate) if rate else None
        base = max(since, self.began)
        return (base + found[0], base + found[1]) if found else None


def heard(rec: Any, since: float, timeout_s: float, watch=None) -> tuple[float, float] | None:
    """The speech span after ``since`` once it ended (``SETTLE_S`` quiet), else ``None``;
    ``watch`` runs at every poll (lane states)."""

    def probe() -> tuple[float, float] | None:
        if watch is not None:
            watch()
        found = rec.span(since)
        return found if found and time.perf_counter() - found[1] >= SETTLE_S else None

    try:
        return ui.wait(probe, timeout_s)
    except TimeoutError:
        return None


def quiet(rec: Any, since: float, until: float) -> bool:
    """Whether ``rec`` had no speech between ``since`` and ``until`` (waits until then)."""
    uia.wait_for(lambda: time.perf_counter() >= until, max(0.0, until - time.perf_counter()) + 1.0)
    return rec.span(since, until) is None
