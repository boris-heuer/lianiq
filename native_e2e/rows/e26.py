"""E-26: Listen & translate session rule, Stop and privacy (CAP-0170 e2e plan E-04, E-06, E-08).

Image models, its own app; fixtures through ``synth.speech_wav`` (all pinned:
``conv_de_16k.wav`` as the one sentence, ``listen_de3_16k.wav``, ``listen_sentinel_16k.wav``
"Lianiq Kontrollsatz QX7 Hörprobe."; ``blocked`` with ``fixture-missing`` otherwise).
German → Mandarin (Simplified), *Microphone* "CABLE Output" (``e14._setup``). **Start
listening**; sidebar **Settings**; one sentence into the cable; back on Listen & translate the
new row is there. Sidebar **Conversation**, F8: refused with "Stop the Listen & translate
session first" while Listen still runs; F9 there stops it; the rows are kept. **Start
listening**; the three sentences, F9 right after them: the first state read within
``AT_ONCE_S`` is *Stopping…* (or already *Stopped*), *Stopped* follows within ``STOP_BOUND_S``
(seconds stored) and the log has "Microphone capture stopped" (capture session closed).
**Start listening**; the sentinel; one translated row; F9; masked screenshot; Settings ›
Diagnostics **Export…** to ``%TEMP%\\lianiq-e2e\\diagnostics-E26.txt``; the app is closed and
started again: *Transcript* empty, German, Mandarin (Simplified) and the cable preselected.
Then ``logs\\``, the export and ``config\\settings*.json`` hold neither "QX7" nor any row text
(counts only), and no ``.wav`` newer than the row's start exists in the checkout or
``%TEMP%`` (junctions, ``models``, ``fixtures`` and ``.git`` skipped). The app is closed and
the settings reset to the S-03 baseline at the end.
"""

from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path

from native_e2e import audio, synth, uia_app
from native_e2e.context import RunContext
from native_e2e.evidence.model import Check, Method, Row
from native_e2e.rows import e10, e14, e15, ui
from native_e2e.rows import listen_flow as lf
from native_e2e.rows.common import blocked_row, check, make_row
from native_e2e.rows.listen_flow import GERMAN, MANDARIN

FIXTURES = ("conv_de_16k.wav", "listen_de3_16k.wav", "listen_sentinel_16k.wav")
SENTINEL = "QX7"
AT_ONCE_S = 2.0  # "Stopping…" without a visible delay (one UIA read may take a second)
STOP_BOUND_S = 40.0
EXPORT_NAME = "diagnostics-E26.txt"
SCREEN = "screens/e26-listen.png"
SKIP_DIRS = {"models", "fixtures", ".git", ".venv", "__pycache__"}
MAX_DEPTH = 4
clock = time.monotonic  # the Stop timer (a test sets the clock)


def _translated_row(app, s, count: int) -> list[str] | None:
    enough = lambda new: any(lf.translated(t, GERMAN, MANDARIN, s) for t in new)
    try:
        return lf.settle(app, s, count, enough)
    except TimeoutError:
        return None


def _settings_visit(ctx, app, s, path: Path, checks: list[Check], texts: list[str]) -> bool:
    if not ui.select(app, s.NAV_SETTINGS, s.NAV_REGION):
        checks.append(check("row-added-during-settings-visit", False, "not-selected"))
        return False
    audio.play_into_cable(path)
    new = _translated_row(app, s, 0) if ui.select(app, s.NAV_LISTEN, s.NAV_REGION) else None
    checks.append(check("row-added-during-settings-visit", bool(new)))
    texts += lf.remember(ctx, new or [], GERMAN, MANDARIN)
    return bool(new)


def _session_rule(app, s, checks: list[Check]) -> bool:
    count = len(lf.rows(app.nodes()))
    running = s.SESSION_RUNNING.format(mode=s.NAV_LISTEN)
    if not ui.select(app, s.NAV_CONVERSATION, s.NAV_REGION):
        checks.append(check("conversation-start-refused", False, "not-selected"))
        return False
    app.keys("{F8}")
    refused = s.SESSION_BUSY.format(mode=s.NAV_LISTEN)
    probe = lambda: ui.shows(app.nodes(), refused) and ui.shows(app.nodes(), running)
    if not ui.waited(checks, "conversation-start-refused", probe):
        return False
    app.keys("{F9}")
    if not ui.waited(checks, "f9-stops-listen", lambda: not ui.shows(app.nodes(), running)):
        return False
    kept = ui.select(app, s.NAV_LISTEN, s.NAV_REGION) and len(lf.rows(app.nodes())) == count
    checks.append(check("rows-kept", kept, f"rows={count}"))
    return kept


def _state(nodes, s) -> str | None:
    if ui.shows(nodes, s.LISTEN_STATE_STOPPING):
        return "stopping"
    return "stopped" if ui.shows(nodes, s.LISTEN_STATE_STOPPED) else None


def _stop_at_once(ctx, app, s, path: Path, checks: list[Check], texts: list[str]) -> bool:
    count = len(lf.rows(app.nodes()))
    if not lf.start(app, s, checks, "session-running-for-stop"):
        return False
    offset = e15.log_size(ctx)
    audio.play_into_cable(path)
    app.keys("{F9}")
    pressed = clock()
    try:
        first = ui.wait(lambda: _state(app.nodes(), s), AT_ONCE_S)
    except TimeoutError:
        first = "none"
    checks.append(check("stopping-at-once", first != "none", f"first={first}"))
    left = max(STOP_BOUND_S - (clock() - pressed), 0.0)  # the bound counts from F9
    try:
        ui.wait(lambda: _state(app.nodes(), s) == "stopped", left)
        seconds = round(clock() - pressed, 1)
    except TimeoutError:
        seconds = None
    within = seconds is not None and seconds <= STOP_BOUND_S
    checks.append(check("stopped-within-40s", within, f"seconds={seconds}"))
    texts += lf.remember(ctx, lf.rows(app.nodes())[count:], GERMAN, MANDARIN)
    closed = lambda: e15.CAPTURE_STOPPED in e15.log_since(ctx, offset)
    return ui.waited(checks, "capture-session-closed", closed) and within


def _sentinel(ctx, app, s, path: Path, checks: list[Check], texts: list[str]) -> bool:
    count = len(lf.rows(app.nodes()))
    if not lf.start(app, s, checks, "session-running-sentinel"):
        return False
    audio.play_into_cable(path)
    new = _translated_row(app, s, count)
    checks.append(check("sentinel-translated", bool(new)))
    texts += lf.remember(ctx, new or [], GERMAN, MANDARIN)
    app.keys("{F9}")
    return bool(new) and ui.waited(checks, "sentinel-stopped", lambda: lf.idle(app.nodes(), s))


def _export(ctx, app, s, checks: list[Check]) -> Path | None:
    path = ctx.temp / EXPORT_NAME
    path.unlink(missing_ok=True)
    if not ui.select(app, s.NAV_SETTINGS, s.NAV_REGION):
        checks.append(check("diagnostics-exported", False, "not-selected"))
        return None
    closed, _answered = e10.export(app, s, path)
    try:
        ui.wait(path.is_file)
    except TimeoutError:
        closed = False
    checks.append(check("diagnostics-exported", closed))
    return path if closed else None


def _restart(ctx, s, checks: list[Check]) -> None:
    app = uia_app.launch(ctx)
    try:
        if not ui.select(app, s.NAV_LISTEN, s.NAV_REGION):
            checks.append(check("restart-transcript-empty", False, "not-selected"))
            return
        nodes = app.nodes()
        checks.append(check("restart-transcript-empty", not lf.rows(nodes)))
        pair = lf.combos(nodes, s) == (lf.name(GERMAN), lf.name(MANDARIN))
        cable = audio.wasapi_name(audio.CABLE_OUTPUT, "input")
        mic = cable is not None and e14._value(nodes, s.LISTEN_MICROPHONE) == cable
        checks.append(check("restart-preselected", pair and mic))
    finally:
        app.close()


def _files(ctx, export: Path | None) -> list[Path]:
    logs = ctx.repo / "logs"
    found = [p for p in logs.rglob("*") if p.is_file()] if logs.is_dir() else []
    found += sorted((ctx.repo / "config").glob("settings*.json"))
    return found + ([export] if export is not None else [])


def _privacy(ctx, export: Path | None, texts: list[str], checks: list[Check]) -> None:
    needles = [SENTINEL, *texts]
    files = _files(ctx, export)
    hits = 0
    for path in files:
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        hits += any(needle in content for needle in needles)
    detail = f"files={len(files)} matches={hits} needles={len(needles)}"
    checks.append(check("no-sentinel-or-row-text", hits == 0 and export is not None, detail))


def new_wavs(roots: list[Path], since: float) -> int:
    """``.wav`` files modified at or after ``since`` below ``roots`` (bounded walk)."""
    count = 0
    for root in roots:
        base = len(root.parts)
        for folder, dirs, names in os.walk(root):
            here = Path(folder)
            dirs[:] = [
                d
                for d in dirs
                if d not in SKIP_DIRS
                and not (here / d).is_junction()
                and len(here.parts) - base < MAX_DEPTH
            ]
            for item in names:
                path = here / item
                try:
                    count += item.lower().endswith(".wav") and path.stat().st_mtime >= since
                except OSError:
                    continue
    return count


def _session(ctx, app, paths, checks: list[Check], artifacts: list, texts: list[str]) -> bool:
    s = ui.strings()
    if not e14._setup(app, s, checks) or not lf.start(app, s, checks, "session-running"):
        return False
    if not _settings_visit(ctx, app, s, paths[0], checks, texts):
        return False
    if not _session_rule(app, s, checks) or not _stop_at_once(ctx, app, s, paths[1], checks, texts):
        return False
    if not _sentinel(ctx, app, s, paths[2], checks, texts):
        return False
    shot, artifact = lf.shot(ctx, app, SCREEN, "screenshot-masked")
    checks.append(shot)
    artifacts.append(artifact)
    ctx.state["e26_export"] = _export(ctx, app, s, checks)
    return True


def run(ctx: RunContext) -> Row:
    paths = [synth.speech_wav(ctx, name) for name in FIXTURES]
    if None in paths:
        missing = ",".join(n for n, p in zip(FIXTURES, paths, strict=True) if p is None)
        return blocked_row("E-26", synth.FIXTURE_MISSING, missing)
    started = time.time() - 1
    checks: list[Check] = [check("fixtures-checked", True)]
    artifacts: list = []
    texts: list[str] = []
    ctx.state.pop("e26_export", None)
    uia_app.close_open(ctx)
    try:
        app = uia_app.launch(ctx)
        try:
            done = _session(ctx, app, paths, checks, artifacts, texts)
        finally:
            app.close()
        if done:
            _restart(ctx, ui.strings(), checks)
            _privacy(ctx, ctx.state.get("e26_export"), texts, checks)
            count = new_wavs([ctx.repo, Path(tempfile.gettempdir())], started)
            checks.append(check("no-new-wav", count == 0, f"count={count}"))
    finally:
        checks.append(check("settings-reset", uia_app.settings_reset(ctx)))
    method = Method.VIRTUAL_DEVICE
    return make_row("E-26", checks, artifacts, reason="listen-rules-privacy", method=method)
