"""E-14: one Listen & translate session through the cable (CAP-0170 AC-31, e2e plan E-09).

The fixture ``native_e2e/fixtures/listen_de_16k.wav`` (two German sentences, Piper
``de_DE-thorsten-medium``, 16 kHz mono 16-bit PCM, about 1 s of silence after each) is
checked against ``FIXTURE_SHA256`` before any app starts. E-14 closes an app an earlier row
left open and starts its own instance. Listen & translate: *Source language* German,
*Target language* Mandarin (Simplified), *Microphone* "CABLE Output" (compared with the
cable's WASAPI name; only ``name_matches`` is stored). **Start listening**, wait until the
page listens (model readiness, 300 s) and the strip shows "Listen & translate running",
play the WAV into "CABLE Input" and wait until *Transcript* shows two or more done rows and
no pending one, recorded once two consecutive reads agree: only a SHA-256 of the
translation texts is stored, never a text. The strip still shows the session; F9 returns
the page to idle (**Start listening** enabled, strip gone). No WASAPI render session of the
app process exists (``audio_sessions``): no output stream was opened. One masked
screenshot; the *Transcript* list is masked whatever it shows. The app is closed.

The row texts stay in memory: in ``ctx.state["transcripts"]`` (screenshot masking) and in
``ctx.secrets`` (also each part alone) so the artifact scan fails on any copy, as in E-03.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from native_e2e import audio, audio_sessions, screens, uia_app
from native_e2e.context import RunContext
from native_e2e.evidence.model import Check, Method, Row
from native_e2e.evidence.sums import file_sha256
from native_e2e.rows import ui
from native_e2e.rows.common import check, make_row
from native_e2e.uia import Node

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "listen_de_16k.wav"
FIXTURE_SHA256 = "b82a5b80f05a5c444b222351875b57e286d456ad2ba927ddd1e057bce702a6cb"
# English registry names (lianiq/languages/registry.py; not in strings.py).
SOURCE, TARGET = "German", "Mandarin (Simplified)"
SCREEN = "screens/e14-listen.png"
MIN_SECRET = 4  # shorter texts are not useful scan needles
DONE_ROWS = 2


def _combo(nodes: list[Node], label: str) -> Node | None:
    return ui.find(nodes, label, "ComboBox")


def _value(nodes: list[Node], label: str) -> str | None:
    combo = _combo(nodes, label)
    return combo.value if combo is not None else None


def _choose(app, label: str, item: str) -> bool:
    """Select ``item`` in the combo ``label`` (if not shown already) and wait for it."""
    if _value(app.nodes(), label) == item:
        return True
    combo = _combo(app.nodes(), label)
    try:
        if combo is None:
            return False
        app.choose(combo, item)
        ui.wait_nodes(app, lambda nodes: _value(nodes, label) == item)
    except Exception:  # noqa: BLE001 - not selectable (UIA/pywinauto error) or timeout
        return False
    return True


def split_row(text: str) -> tuple[str, str] | None:
    """(source, outcome) of a row's accessible text "<time>, <src>: <text>. <tgt>: <out>"."""
    head, sep, outcome = text.rpartition(f". {TARGET}: ")
    if not sep:
        lines = text.splitlines()  # the display text: heading, source, outcome
        return (lines[1], lines[-1]) if len(lines) >= 3 else None
    return head.partition(f"{SOURCE}: ")[2], outcome


def rows(nodes: list[Node]) -> list[str]:
    """The texts of the shown *Transcript* rows, in tree order."""
    title = ui.strings().LISTEN_TRANSCRIPT
    return [
        node.name
        for node in nodes
        if node.visible and node.control_type == "ListItem" and title in node.parents
    ]


def _pending(s: Any) -> tuple[str, ...]:
    failed = s.LISTEN_SEGMENT_FAILED.split("{reason}")[0]
    return (
        s.LISTEN_RECOGNIZING,
        s.LISTEN_TRANSLATING,
        s.LISTEN_NOT_UNDERSTOOD,
        s.LISTEN_SKIPPED,
        s.LISTEN_NOT_FINISHED,
        failed,
    )


def done_rows(texts: list[str], s: Any) -> list[tuple[str, str]] | None:
    """(source, translation) per row once every row is done, else ``None``."""
    parts = [split_row(text) for text in texts]
    pending = _pending(s)
    if not parts or any(
        part is None or not part[1].strip() or part[1].startswith(pending) for part in parts
    ):
        return None
    return parts  # type: ignore[return-value]


def _settled(app, s: Any) -> tuple[list[str], list[tuple[str, str]]]:
    """Rows once two or more are done and two consecutive reads agree (``TimeoutError``)."""
    last: list[list[str]] = []

    def probe() -> tuple[list[str], list[tuple[str, str]]] | None:
        current = rows(app.nodes())
        done = done_rows(current, s)
        stable = bool(last) and last[-1] == current
        last[:] = [current]
        return (current, done) if stable and done and len(done) >= DONE_ROWS else None

    return ui.wait(probe, ui.MODEL_TIMEOUT_S)


def digest(translations: list[str]) -> str:
    return hashlib.sha256("\n".join(translations).encode("utf-8")).hexdigest()


def _remember(ctx: RunContext, texts: list[str], done: list[tuple[str, str]]) -> None:
    kept = ctx.state.setdefault("transcripts", [])
    for text in [*texts, *(part for pair in done for part in pair)]:
        text = text.strip()
        if text and text not in kept:
            kept.append(text)
        if len(text) >= MIN_SECRET and text not in ctx.secrets:
            ctx.secrets.append(text)


def _idle(nodes: list[Node], s: Any, running: str) -> bool:
    start = ui.find(nodes, s.LISTEN_START, "Button")
    return start is not None and start.enabled and not ui.shows(nodes, running)


def _no_render(app) -> Check:
    try:
        opened = audio_sessions.render_pids() & set(app.pids())
    except Exception as error:  # noqa: BLE001 - COM unavailable: the row cannot prove it
        return check("no-render-stream", False, type(error).__name__)
    return check("no-render-stream", not opened, f"render_sessions={len(opened)}")


def screenshot(ctx: RunContext, app, s: Any) -> tuple[Check, Any]:
    """Masked like ``ui.screenshot``, with the whole *Transcript* list masked too."""
    names = [*audio.endpoint_names(), *ui.transcript_needles(ctx.state.get("transcripts", []))]
    combos = (s.LISTEN_MICROPHONE, s.NOTICE_MICROPHONE, s.NOTICE_SPEAKERS)
    fields = screens.TRANSCRIPT_FIELDS  # also the Listen *Transcript* list

    def rects() -> list:
        return screens.mask_rects(app.nodes(), names, combos, fields)

    before, window = rects(), app.rect
    png = screens.grab(window)
    found = list(dict.fromkeys(before + rects()))
    artifact = screens.write_masked(ctx, SCREEN, png, window[:2], found)
    return check("screenshot-masked", True, f"masked={len(found)}"), artifact


def _setup(app, s: Any, checks: list[Check]) -> bool:
    if not ui.select(app, s.NAV_LISTEN, s.NAV_REGION):
        checks.append(check("listen-selected", False, "not-selected"))
        return False
    pair = _choose(app, s.LISTEN_SOURCE_LANGUAGE, SOURCE)
    pair = pair and _choose(app, s.LISTEN_TARGET_LANGUAGE, TARGET)
    checks.append(check("pair-german-to-mandarin", pair))
    expected = audio.wasapi_name(audio.CABLE_OUTPUT, "input")
    matches = expected is not None and _choose(app, s.LISTEN_MICROPHONE, expected)
    checks.append(check("microphone-cable-selected", matches, f"name_matches: {matches!r}".lower()))
    return pair and matches


def _session(ctx: RunContext, app, checks: list[Check], artifacts: list) -> None:
    s = ui.strings()
    running = s.SESSION_RUNNING.format(mode=s.NAV_LISTEN)
    if not _setup(app, s, checks):
        return
    start = ui.find(app.nodes(), s.LISTEN_START, "Button")
    if start is None or not start.enabled:
        checks.append(check("start-listening", False, "not-enabled"))
        return
    app.press(start)
    checks.append(check("start-listening", True))

    def listening() -> bool:
        nodes = app.nodes()
        state = ui.shows(nodes, s.LISTEN_STATE_LISTENING) or ui.shows(
            nodes, s.LISTEN_STATE_PROCESSING
        )
        return state and ui.shows(nodes, running)

    if not ui.waited(checks, "session-running", listening, ui.MODEL_TIMEOUT_S):
        return
    audio.play_into_cable(FIXTURE)
    try:
        texts, done = _settled(app, s)
    except TimeoutError:
        checks.append(check("two-done-rows", False, "timeout"))
        return
    _remember(ctx, texts, done)
    translations = [translation for _source, translation in done]
    checks += [
        check("two-done-rows", True, f"rows={len(done)}"),
        check("translations-sha256", True, f"sha256={digest(translations)}"),
        check("strip-shows-running", ui.shows(app.nodes(), running)),
    ]
    app.keys("{F9}")
    if not ui.waited(checks, "stopped-with-f9", lambda: _idle(app.nodes(), s, running)):
        return
    checks.append(_no_render(app))
    shot, artifact = screenshot(ctx, app, s)
    checks.append(shot)
    artifacts.append(artifact)


def run(ctx: RunContext) -> Row:
    if not FIXTURE.is_file() or file_sha256(FIXTURE) != FIXTURE_SHA256:
        checks = [check("listen-fixture-sha256", False)]
        return make_row("E-14", checks, reason="listen-fixture", method=Method.VIRTUAL_DEVICE)
    checks: list[Check] = [check("listen-fixture-sha256", True)]
    artifacts: list = []
    uia_app.close_open(ctx)  # an app left open by an earlier row: E-14 needs its own
    app = uia_app.launch(ctx)
    try:
        _session(ctx, app, checks, artifacts)
    finally:
        app.close()
    return make_row(
        "E-14", checks, artifacts, reason="listen-session", method=Method.VIRTUAL_DEVICE
    )
